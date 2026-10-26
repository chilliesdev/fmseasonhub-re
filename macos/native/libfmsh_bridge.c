/*
 * libfmsh_bridge.c - macOS Mach VM Memory Bridge & UNIX Domain Socket IPC Server
 * 
 * Provides:
 * 1. Direct C bindings for Mach VM APIs (task_for_pid, mach_vm_read_overwrite, mach_vm_region)
 * 2. Background UNIX Domain Socket IPC Server on /tmp/fmsh_mem_bridge.sock
 *
 * Can be compiled as universal dylib (arm64 + x86_64) or executed directly.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <unistd.h>
#include <errno.h>
#include <pthread.h>
#include <poll.h>
#include <fcntl.h>
#include <stdatomic.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <mach-o/dyld.h>

#ifndef FMSH_SOCKET_PATH
#define FMSH_SOCKET_PATH "/tmp/fmsh_mem_bridge.sock"
#endif
#define FMSH_BUFFER_SIZE 65536

static mach_port_t g_target_task = MACH_PORT_NULL;
static pid_t g_target_pid = 0;
static pthread_mutex_t g_task_mutex = PTHREAD_MUTEX_INITIALIZER;

static pthread_t g_server_thread;
static atomic_bool g_server_running = false;

/* =========================================================================
 * Mach VM Direct APIs (Callable via ctypes / C linking)
 * ========================================================================= */

__attribute__((visibility("default")))
int fmsh_attach(pid_t pid) {
    pthread_mutex_lock(&g_task_mutex);
    if (pid <= 0 || pid == getpid()) {
        g_target_task = mach_task_self();
        g_target_pid = getpid();
        pthread_mutex_unlock(&g_task_mutex);
        return 0;
    }

    if (g_target_task != MACH_PORT_NULL && g_target_task != mach_task_self()) {
        mach_port_deallocate(mach_task_self(), g_target_task);
        g_target_task = MACH_PORT_NULL;
        g_target_pid = 0;
    }

    mach_port_t task = MACH_PORT_NULL;
    kern_return_t kr = task_for_pid(mach_task_self(), pid, &task);
    if (kr != KERN_SUCCESS) {
        pthread_mutex_unlock(&g_task_mutex);
        return (int)kr;
    }

    g_target_task = task;
    g_target_pid = pid;
    pthread_mutex_unlock(&g_task_mutex);
    return 0;
}

__attribute__((visibility("default")))
void fmsh_detach(void) {
    pthread_mutex_lock(&g_task_mutex);
    if (g_target_task != MACH_PORT_NULL && g_target_task != mach_task_self()) {
        mach_port_deallocate(mach_task_self(), g_target_task);
    }
    g_target_task = MACH_PORT_NULL;
    g_target_pid = 0;
    pthread_mutex_unlock(&g_task_mutex);
}

__attribute__((visibility("default")))
int fmsh_is_attached(void) {
    pthread_mutex_lock(&g_task_mutex);
    int attached = (g_target_task != MACH_PORT_NULL) ? 1 : 0;
    pthread_mutex_unlock(&g_task_mutex);
    return attached;
}

__attribute__((visibility("default")))
pid_t fmsh_get_attached_pid(void) {
    pthread_mutex_lock(&g_task_mutex);
    pid_t pid = g_target_pid;
    pthread_mutex_unlock(&g_task_mutex);
    return pid;
}

__attribute__((visibility("default")))
size_t fmsh_read(uint64_t addr, void *buf, size_t size) {
    pthread_mutex_lock(&g_task_mutex);
    if (g_target_task == MACH_PORT_NULL || !buf || size == 0) {
        pthread_mutex_unlock(&g_task_mutex);
        return 0;
    }

    mach_vm_size_t out_size = 0;
    kern_return_t kr = mach_vm_read_overwrite(
        g_target_task,
        (mach_vm_address_t)addr,
        (mach_vm_size_t)size,
        (mach_vm_address_t)buf,
        &out_size
    );

    pthread_mutex_unlock(&g_task_mutex);
    if (kr != KERN_SUCCESS) {
        return 0;
    }
    return (size_t)out_size;
}

__attribute__((visibility("default")))
size_t fmsh_get_regions(uint64_t *out_addrs, uint64_t *out_sizes, size_t max_count) {
    pthread_mutex_lock(&g_task_mutex);
    if (g_target_task == MACH_PORT_NULL || !out_addrs || !out_sizes || max_count == 0) {
        pthread_mutex_unlock(&g_task_mutex);
        return 0;
    }

    mach_vm_address_t addr = 0;
    mach_vm_size_t size = 0;
    natural_t depth = 0;
    vm_region_submap_info_data_64_t info;
    mach_msg_type_number_t count = VM_REGION_SUBMAP_INFO_COUNT_64;
    size_t found = 0;

    while (found < max_count) {
        kern_return_t kr = mach_vm_region_recurse(
            g_target_task,
            &addr,
            &size,
            &depth,
            (vm_region_recurse_info_t)&info,
            &count
        );
        if (kr != KERN_SUCCESS) {
            break;
        }

        if (info.is_submap) {
            depth++;
            continue;
        }

        // Only include readable regions
        if ((info.protection & VM_PROT_READ) != 0) {
            out_addrs[found] = (uint64_t)addr;
            out_sizes[found] = (uint64_t)size;
            found++;
        }

        addr += size;
    }

    pthread_mutex_unlock(&g_task_mutex);
    return found;
}

/* =========================================================================
 * UNIX Domain Socket IPC Server (/tmp/fmsh_mem_bridge.sock)
 * ========================================================================= */

static uint64_t get_image_base(const char *target) {
    uint32_t count = _dyld_image_count();
    if (target && strlen(target) > 0) {
        for (uint32_t i = 0; i < count; i++) {
            const char *name = _dyld_get_image_name(i);
            if (name && strstr(name, target) != NULL) {
                return (uint64_t)_dyld_get_image_header(i);
            }
        }
        return 0;
    }
    // An empty target explicitly requests the main executable.
    if (count > 0) {
        return (uint64_t)_dyld_get_image_header(0);
    }
    return 0;
}

/* SIGPIPE belongs to the host. Suppress it only on bridge sockets. */
static int accept_client(int server_fd) {
    int fd = accept(server_fd, NULL, NULL);
    if (fd >= 0) {
        int enabled = 1;
        if (setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &enabled, sizeof(enabled)) < 0 ||
            fcntl(fd, F_SETFL, O_NONBLOCK) < 0) {
            close(fd);
            return -1;
        }
    }
    return fd;
}

/* Keep admission responsive even during an incomplete command or slow read. */
static bool wait_for_client(int client_fd, int server_fd, short events) {
    while (g_server_running) {
        struct pollfd fds[] = {
            { .fd = client_fd, .events = events },
            { .fd = server_fd, .events = POLLIN }
        };
        int ready = poll(fds, 2, 100);
        if (ready < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        if (!g_server_running) return false;
        /* Release an already closed reader before deciding the server is busy. */
        if ((fds[1].revents & POLLIN) && (events & POLLIN) &&
            (fds[0].revents & POLLIN)) {
            char byte;
            ssize_t n = recv(client_fd, &byte, 1, MSG_PEEK | MSG_DONTWAIT);
            if (n == 0) return true;
        }
        if (fds[1].revents & POLLIN) {
            int busy_fd = accept_client(server_fd);
            if (busy_fd >= 0) {
                const char busy[] = "ERR_BUSY\n";
                /* Never block the active client on a rejected peer. */
                send(busy_fd, busy, sizeof(busy) - 1, MSG_DONTWAIT);
                close(busy_fd);
            }
        }
        if (fds[1].revents & (POLLERR | POLLHUP | POLLNVAL)) return false;
        if (fds[0].revents & (events | POLLERR | POLLHUP | POLLNVAL)) return true;
    }
    return false;
}

static bool write_response(int client_fd, int server_fd, const void *data, size_t size) {
    const uint8_t *bytes = data;
    size_t sent = 0;
    while (sent < size && g_server_running) {
        ssize_t n = send(client_fd, bytes + sent, size - sent, MSG_DONTWAIT);
        if (n > 0) {
            sent += (size_t)n;
        } else if (n < 0 && errno == EINTR) {
            continue;
        } else if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            if (!wait_for_client(client_fd, server_fd, POLLOUT)) return false;
        } else {
            return false;
        }
    }
    return sent == size;
}

static void handle_client(int client_fd, int server_fd) {
    char line[512];
    uint8_t read_buffer[FMSH_BUFFER_SIZE];

    while (g_server_running) {
        // Read line command
        ssize_t idx = 0;
        char c;
        while (idx < (ssize_t)sizeof(line) - 1) {
            if (!wait_for_client(client_fd, server_fd, POLLIN)) {
                close(client_fd);
                return;
            }
            ssize_t r = recv(client_fd, &c, 1, MSG_DONTWAIT);
            if (r < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) continue;
            if (r <= 0) {
                close(client_fd);
                return;
            }
            if (c == '\n') break;
            if (c != '\r') line[idx++] = c;
        }
        line[idx] = '\0';

        if (strcmp(line, "PING") == 0) {
            const char *resp = "PONG\n";
            if (!write_response(client_fd, server_fd, resp, strlen(resp))) break;
        } else if (strncmp(line, "ATTACH ", 7) == 0) {
            pid_t pid = (pid_t)atoi(line + 7);
            int res = fmsh_attach(pid);
            if (res == 0) {
                const char *resp = "OK\n";
                if (!write_response(client_fd, server_fd, resp, strlen(resp))) break;
            } else {
                char resp[64];
                snprintf(resp, sizeof(resp), "ERR %d\n", res);
                if (!write_response(client_fd, server_fd, resp, strlen(resp))) break;
            }
        } else if (strcmp(line, "DETACH") == 0) {
            fmsh_detach();
            const char *resp = "OK\n";
            if (!write_response(client_fd, server_fd, resp, strlen(resp))) break;
        } else if (strcmp(line, "IS_ATTACHED") == 0) {
            int att = fmsh_is_attached();
            char resp[32];
            snprintf(resp, sizeof(resp), "%d\n", att);
            if (!write_response(client_fd, server_fd, resp, strlen(resp))) break;
        } else if (strncmp(line, "GET_BASE", 8) == 0) {
            const char *modname = "";
            if (strlen(line) > 8) {
                modname = line + 8;
                while (*modname == ' ') modname++;
            }
            uint64_t base = get_image_base(modname);
            char resp[64];
            snprintf(resp, sizeof(resp), "OK %llx\n", (unsigned long long)base);
            if (!write_response(client_fd, server_fd, resp, strlen(resp))) break;
        } else if (strncmp(line, "READ ", 5) == 0) {
            uint64_t addr = 0;
            size_t size = 0;
            if (sscanf(line + 5, "%llx %zu", (unsigned long long *)&addr, &size) == 2) {
                if (size > sizeof(read_buffer)) {
                    // Send error if size too large for single frame
                    const char *resp = "ERR_TOO_LARGE\n";
                    if (!write_response(client_fd, server_fd, resp, strlen(resp))) break;
                    continue;
                }
                size_t n = fmsh_read(addr, read_buffer, size);
                if (n == size) {
                    char header[64];
                    int hlen = snprintf(header, sizeof(header), "OK %zu\n", n);
                    if (!write_response(client_fd, server_fd, header, (size_t)hlen) ||
                        !write_response(client_fd, server_fd, read_buffer, n)) break;
                } else {
                    const char *resp = "ERR_READ\n";
                    if (!write_response(client_fd, server_fd, resp, strlen(resp))) break;
                }
            } else {
                const char *resp = "ERR_SYNTAX\n";
                if (!write_response(client_fd, server_fd, resp, strlen(resp))) break;
            }
        } else if (strcmp(line, "QUIT") == 0) {
            break;
        } else {
            const char *resp = "ERR_UNKNOWN\n";
            if (!write_response(client_fd, server_fd, resp, strlen(resp))) break;
        }
    }
    close(client_fd);
}

static void *server_worker(void *arg) {
    (void)arg;
    unlink(FMSH_SOCKET_PATH);

    int sfd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (sfd < 0) {
        g_server_running = false;
        return NULL;
    }
    if (fcntl(sfd, F_SETFL, O_NONBLOCK) < 0) {
        close(sfd);
        g_server_running = false;
        return NULL;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, FMSH_SOCKET_PATH, sizeof(addr.sun_path) - 1);

    if (bind(sfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(sfd);
        g_server_running = false;
        return NULL;
    }

    chmod(FMSH_SOCKET_PATH, 0777);

    if (listen(sfd, 16) < 0) {
        close(sfd);
        g_server_running = false;
        return NULL;
    }

    while (g_server_running) {
        struct pollfd listener = { .fd = sfd, .events = POLLIN };
        int ready = poll(&listener, 1, 100);
        if (!g_server_running) break;
        if (ready < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (ready == 0) continue;
        if (!(listener.revents & POLLIN)) break;
        int cfd = accept_client(sfd);
        if (cfd < 0) {
            if (!g_server_running) break;
            continue;
        }
        handle_client(cfd, sfd);
    }

    close(sfd);
    unlink(FMSH_SOCKET_PATH);
    return NULL;
}

__attribute__((visibility("default")))
int fmsh_start_socket_server(void) {
    if (g_server_running) return 0;
    g_server_running = true;
    if (pthread_create(&g_server_thread, NULL, server_worker, NULL) != 0) {
        g_server_running = false;
        return -1;
    }
    return 0;
}

__attribute__((visibility("default")))
void fmsh_stop_socket_server(void) {
    if (!g_server_running) return;
    g_server_running = false;
    pthread_join(g_server_thread, NULL);
    unlink(FMSH_SOCKET_PATH);
}

__attribute__((constructor))
static void fmsh_injected_init(void) {
    const char *dyld_insert = getenv("DYLD_INSERT_LIBRARIES");
    if (dyld_insert && strstr(dyld_insert, "libfmsh_bridge") != NULL) {
        pthread_mutex_lock(&g_task_mutex);
        g_target_task = mach_task_self();
        g_target_pid = getpid();
        pthread_mutex_unlock(&g_task_mutex);
        fmsh_start_socket_server();
    }
}

__attribute__((destructor))
static void fmsh_injected_fini(void) {
    const char *dyld_insert = getenv("DYLD_INSERT_LIBRARIES");
    if (dyld_insert && strstr(dyld_insert, "libfmsh_bridge") != NULL) {
        fmsh_stop_socket_server();
    }
}
