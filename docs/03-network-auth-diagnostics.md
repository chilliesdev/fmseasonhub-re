# Network API, Authentication Architecture, and Diagnostics Analysis
**Target Application:** FM Season Hub (FMSH) v0.8.2.1  
**Target Environment:** Windows x64 (Python 3.14 + Nuitka Ahead-of-Time Compiled C Extensions)  
**Analysis Scope:** Network Endpoints, Licensing/Auth Architecture, Update Protocol, Diagnostics Utility, Installer Metadata  
**Compliance Standard:** Architectural documentation and protocol specification only; strictly no DRM bypass or exploit implementation.

---

## 1. Executive Architecture Summary

FM Season Hub (FMSH) v0.8.2.1 employs a hybrid offline-first architecture:
- Core game analysis, memory reading, and database operations execute **100% locally**.
- Network interaction is strictly constrained to a single Cloudflare Worker endpoint (`https://fmsh-acesso.marcellofelipe90.workers.dev`), an asset/dashboard domain (`painel.fmseasonhub.com`), and GitHub release distribution proxied via Worker.
- Licensing and supporter tier verification uses a stateless cloud token/ticket resolution model paired with a hardware-stable machine hash. Offline operation is fully maintained via caching and graceful degradation; network unavailability never blocks application startup or core functionality.
- Security and integrity checks use public-key cryptography (RSA PKCS#1 v1.5 with SHA-256) embedded natively within compiled Nuitka C modules (`assinatura.pyd`, `chaves_publicas.pyc`) to authenticate application updates and plugin packages.

```
+----------------------------------------------------------------------------------------------------+
|                                         FM Season Hub Client                                       |
|                                                                                                    |
|  +--------------------+    +--------------------+    +--------------------+    +----------------+  |
|  |  Local UI / Webview|    |  FastAPI Server    |    |  acesso.pyd        |    |  assinatura.pyd|  |
|  |  (HTML5 / React)   |<-->|  (127.0.0.1:port)  |<-->|  (Auth & Tiers)    |<-->|  (RSA PKCS#1)  |  |
|  +--------------------+    +--------------------+    +--------------------+    +----------------+  |
|                                                                                        |           |
|  +--------------------+    +--------------------+    +--------------------+            |           |
|  |  FMSH-Diagnostico  |    |  atualizacao.pyd   |    |  plugins_atualiz.  |            |           |
|  |  (System & Memory) |    |  (Update Checker)  |    |  (BepInEx Manager) |            |           |
|  +--------------------+    +--------------------+    +--------------------+            |           |
+--------------------------------------|-------------------------|-----------------------|-----------+
                                       | HTTPS                   | HTTPS                 |
                                       v                         v                       v
                    +----------------------------------------------------------------------+
                    |        Cloudflare Worker (fmsh-acesso.marcellofelipe90.workers.dev)  |
                    |                                                                      |
                    |   /resgatar           /patreon/ticket        /versao (GitHub proxy)  |
                    |   /revalidar          /patreon/entrar        /plugins/catalogo       |
                    |   /avisos             /apoiadores                                    |
                    +----------------------------------------------------------------------+
                                       |                         |
                                       v                         v
                           +----------------------+   +----------------------+
                           |  Patreon API OAuth   |   | GitHub API Releases  |
                           +----------------------+   +----------------------+
```

---

## 2. External Network Endpoints & Protocol Specification

### 2.1 Remote Domains and Service Roles

| Domain | Role | Security / Verification |
| :--- | :--- | :--- |
| `https://fmsh-acesso.marcellofelipe90.workers.dev` | Primary backend API (Cloudflare Worker). Handles auth, key redemption, Patreon ticket exchange, updates, announcements, supporters, and plugin catalogs. | TLS 1.3; payload signed with RSA private key where executable content is involved. |
| `https://painel.fmseasonhub.com` | Primary CDN and web portal. Serves plugin screenshots, static documentation, and UI assets. | HTTPS; domain whitelist enforced in `plugins_atualizador.pyd` (max 300 KB per asset). |
| `https://www.patreon.com/16519124/join` | Supporter membership portal. | Standard web browser OAuth redirect. |
| `https://x.com/FMSeasonHub` | Official social media link embedded in UI footer. | Outbound user browser navigation. |
| `https://www.instant-gaming.com/br/23818-comprar-football-manager-27-pc-mac-steam/?igr=fmsh` | Commercial affiliate link for FM27 pre-orders in frontend bundle. | Outbound user browser navigation. |

### 2.2 Cloudflare Worker API Specification

All worker requests enforce:
- HTTP Method: `POST` (auth/tickets/redemptions) or `GET` (avisos/apoiadores/versao/plugins).
- Header `User-Agent: FMSH/<VERSION>` (e.g., `FMSH/0.8.2.1`).
- Header `Content-Type: application/json` on POST requests.
- Fail-safe rule: Network timeouts or HTTP errors never throw unhandled exceptions. All worker callers return a `(dados, erro)` tuple where `dados` is `None` on failure and application logic degrades gracefully.

#### Endpoint Inventory

1. **`POST /resgatar`**
   - **Purpose:** Redeem a single-use access code.
   - **Request Payload:**
     ```json
     {
       "chave": "<USER_ENTERED_KEY>",
       "maquina": "<SHA256_MACHINE_HASH>",
       "versao": "0.8.2.1"
     }
     ```
   - **Response Payload (Success):**
     ```json
     {
       "nivel": 4,
       "tier": "pro",
       "nome_tier": "FMSH Pro",
       "origem": "codigo",
       "chave": "<REDEEMED_KEY>",
       "expirado": false
     }
     ```
   - **Error Conditions:** Invalid key, key exhausted (>2 machines), key revoked.

2. **`GET /patreon/entrar?state=<STATE_PARAM>`**
   - **Purpose:** Browser-based Patreon OAuth flow initiation.
   - **State Construction:** Contains local HTTP loopback port (default 8000), client nonce, and machine hash.
   - **Flow:** User completes OAuth on Patreon; worker issues a single-use opaque `ticket` and redirects back to `http://127.0.0.1:<LOCAL_PORT>/patreon/callback?ticket=<TICKET>`.

3. **`POST /patreon/ticket`**
   - **Purpose:** Complete Patreon authentication by exchanging one-time ticket.
   - **Architecture Rationale:** The client never trusts the redirect URL query parameters for tier level. The local server receives only the opaque ticket and immediately queries `/patreon/ticket` directly via HTTPS POST.
   - **Request Payload:**
     ```json
     {
       "ticket": "<ONE_TIME_TICKET>",
       "maquina": "<SHA256_MACHINE_HASH>"
     }
     ```
   - **Response Payload:** Supporter tier, active pledge status, and expiration.

4. **`POST /revalidar`**
   - **Purpose:** Periodic 7-day synchronization of Patreon membership status.
   - **Request Payload:**
     ```json
     {
       "maquina": "<SHA256_MACHINE_HASH>",
       "versao": "0.8.2.1"
     }
     ```
   - **Behavior:** Re-evaluates subscription status on Patreon backend. If offline, the client continues with cached access.

5. **`GET /versao`**
   - **Purpose:** Checks for new application updates.
   - **Backend Mechanism:** Worker queries GitHub Releases API on behalf of the client and caches responses for several hours. This prevents client IP tracking by GitHub and avoids triggering privacy policy updates.
   - **Response Payload:** Contains latest release version tag and signed manifest.

6. **`GET /plugins/catalogo`**
   - **Purpose:** Retrieves the manifest of verified BepInEx plugins.
   - **Request Headers:** `X-FMSH-Plugins: <id>@<version>,...` (passes current plugin IDs and versions; transmits no machine ID or user telemetry).
   - **Response Payload:** Cryptographically signed JSON array of available plugins, hashes, compatible game versions, and download URLs.

7. **`GET /avisos`**
   - **Purpose:** Announcement billboard feed.
   - **Response:** JSON list of notices with IDs, priority levels, target language keys, title, markdown body, and action buttons.

8. **`GET /apoiadores?nivel=<NIVEL_CREDITOS>`**
   - **Purpose:** Supporter list for the credits roll screen.
   - **Response:** JSON array of public Patreon backer display names.

---

## 3. Supporter & Authentication Architecture

### 3.1 Machine Fingerprinting (`impressao_maquina`)

Implemented in `acesso.pyd`:
- **Entropy Sources:**
  1. Primary: Windows Registry key `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography\MachineGuid` (queried via `winreg` using `KEY_READ | KEY_WOW64_64KEY`).
  2. Fallback: Network MAC address node via `uuid.getnode()` and current OS username via `getpass.getuser()`.
- **Derivation Function:**
  ```python
  raw_id = machine_guid.strip().encode('utf-8')
  hash_payload = raw_id + b'|fmsh'
  machine_hash = hashlib.sha256(hash_payload).hexdigest()
  ```
- **Privacy & Architectural Invariants:**
  - Raw hardware/OS identifiers never traverse the network.
  - The hash allows the server to verify device pairing without identifying the user or hardware configuration.
  - **Machine Limit Policy:** Exactly **2 machines** allowed per access key. This accommodates OS reinstallations (which generate a new `MachineGuid`) without penalizing legitimate users.

### 3.2 Access Levels and Tier Progression

Defined in `limites.pyd` and `acesso.pyd`:
- **Access Tiers:**
  - `0`: Free / Community Tier (`free`)
  - `1 - 3`: Intermediate Supporter Tiers
  - `4`: Top Tier (`FMSH Pro` / `full`)
- **Legacy Migration:** Previous versions (< 0.7) utilized a binary switch (`free`/`full`). On startup, `_nivel_guardado()` automatically upgrades legacy `full` holders to tier 4 (`NIVEL_MAXIMO`).
- **Enforcement Boundaries:** Features (such as high-volume career snapshot storage, Moneyball advanced views, and continuous background sync) query `limites.pode_salvar(escopo, carreira)` before execution. If tier downgraded, existing snapshots are never deleted; only new saves are blocked.

### 3.3 State Machine and Revalidation Lifecycle

```
[Start App]
     |
     v
[Load Local Settings] (fmsh_settings.json)
     |
     +---> Check Origin ('codigo' vs 'patreon')
              |
              +--> 'codigo': Persistent key. Does not expire.
              |
              +--> 'patreon': Check seconds since last verification.
                      |
                      +--> < 7 Days (SEGUNDOS_ATE_RECONFERIR): Keep cached tier.
                      |
                      +--> >= 7 Days: Trigger background POST /revalidar.
                              |
                              +--> Online & Active: Refresh timestamp.
                              +--> Online & Inactive: Downgrade tier.
                              +--> Offline / Network Error: Maintain grace period.
                                   (Offline state NEVER revokes access).
```

### 3.4 Local State Storage

Authentication status is persisted within `fmsh_settings.json` in the user data directory:
- `acesso_nivel`: Current integer tier level (0 to 4).
- `acesso_origem`: Activation source (`"codigo"` or `"patreon"`).
- `acesso_chave`: Masked or plain access code.
- `acesso_maquina`: Cached SHA-256 machine hash.
- `acesso_conferido`: ISO-8601 timestamp or date of last remote handshake.
- `acesso_tier_nome`: Localized tier name string (`"FMSH Pro"`).

---

## 4. Cryptographic Signature Verification (`assinatura` & `chaves_publicas`)

### 4.1 Cryptographic Primitives

Implemented in `assinatura.pyd` with key constants in `chaves_publicas.pyc`:
- **Scheme:** RSA PKCS#1 v1.5 with SHA-256 hash formatting.
- **Verification Implementation:** Pure mathematical Python/C implementation without third-party OpenSSL cryptography bindings:
  $$\text{decrypted} = \text{pow}(\text{signature\_int}, \text{EXPOENTE}, \text{MODULO})$$
- **Public Exponent:** `65537` (`0x10001`).
- **Dual Key Rotation Model:** Two moduli are compiled into `chaves_publicas.pyc`:
  - `MODULOS['atual']`: Primary active RSA modulus.
  - `MODULOS['reserva']`: Backup RSA modulus for disaster recovery / key rollover.

```
Modulus 'atual' (1157 decimal digits, 3840+ bits):
355973677649617121011042936445551020877178626195037761150119282222183794241610128443...

Modulus 'reserva' (1157 decimal digits, 3840+ bits):
405838455996817795768303962625478215102956825054904085579428109659487285558147532549...
```

### 4.2 Signed Manifest Protocol (`atualizacao.pyd`)

Update metadata returned by `/versao` consists of a manifest string and a hexadecimal signature string:
```
+-----------------------------------------------------------------------------+
| Remote Manifest (Plain Text JSON)                                           |
| {                                                                           |
|   "versao": "0.8.2.1",                                                      |
|   "sha256": "3a4f...5e89",                                                  |
|   "tamanho": 31457280,                                                      |
|   "url": "https://github.com/marceloouw/.../FM.Season.Hub.Setup.exe"        |
| }                                                                           |
+-----------------------------------------------------------------------------+
                                       |
                   RSA PKCS#1 v1.5 SHA-256 Signature
                                       |
                                       v
[assinatura.validar(manifesto_bytes, assinatura_bytes, chaves_publicas.MODULOS)]
                                       |
                     +-----------------+-----------------+
                     | Pass                              | Fail
                     v                                   v
          Proceed with Download             Log error & drop update silently
```

Verification occurs in two mandatory phases:
1. **Manifest Integrity:** `assinatura.validar(manifesto, assinatura)` guarantees the manifest was created by the developer's private key.
2. **Binary Integrity:** Once the installer binary is downloaded to `PASTA_DOWNLOAD`, its exact byte size and SHA-256 digest are computed and verified against the validated manifest. Mismatches abort installation immediately.

---

## 5. Auto-Updater & Plugin Distribution Subsystem

### 5.1 Application Updater Protocol

- **Module:** `atualizacao.pyd`
- **Cache File:** `fmsh_versao.json` (TTL: 12 hours for background notification; 0 TTL on explicit check).
- **Execution Mechanism:**
  - Evaluates whether the application is running from an Inno Setup installed environment by verifying the existence of `unins000.exe` and querying `HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\{7081324C-BDD5-4E77-B3D1-05C7DEDBC360}_is1`.
  - Releases single-instance application mutex (`soltar_trava()`).
  - Launches installer subprocess in silent mode with the relaunch switch:
    `"FM Season Hub Setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /reabrir=1`
  - The installer waits for the old `FMSH.exe` process to terminate, replaces files, and restarts the application.

### 5.2 BepInEx Plugin Management (`plugins_atualizador.pyd`)

- **Catalog Endpoint:** `/plugins/catalogo`
- **Managed Plugins:**
  1. `FMActionLink.FMSH`: In-game player profile integration.
  2. `FMActionLink.Kits3D`: 3D kits renderer in club profiles.
  3. `FMActionLink.Stadiums3D`: 3D custom stadium viewer (integration with bassyboy custom stadiums).
  4. `TacticalCam`: Match tactical camera angle and ball scale modifier.
  5. `PitchHUD`: Live on-pitch player stats (distance, passes) with F11 config overlay.
  6. `EasyTrainingTalks`: Bulk squad training praise/criticism automation.
- **Rollout Rings ("Anel"):** Each client randomly selects an integer between `0` and `99` on first installation, persisted locally in `plugins_estado.json`. Staged rollouts target subsets of rings without server tracking.
- **Atomic Replacement & Rollback Safety:**
  - If Football Manager (`fm.exe`) is running, Windows prevents replacing loaded DLLs. The updater performs an atomic rename: `PluginName.dll -> PluginName.antiga`.
  - New binary is written in place. On subsequent launch, BepInEx loads the updated DLL.
  - On the next launch, `plugins_atualizador` inspects BepInEx's `LogOutput.log`. If the plugin failed to load properly, it automatically rolls back from `plugins_anterior/` and marks the version as defective for that system.
  - Inter-process locking with `shared/PluginAutoUpdater.cs` uses `.atualizando` lock file.

---

## 6. Remote Configuration & Announcements

### 6.1 Remote Announcements (`avisos.pyc`)

- **Service Endpoint:** `https://fmsh-acesso.marcellofelipe90.workers.dev/avisos`
- **Local Storage:** `paths.local_data_path('fmsh_avisos.json')`
- **TTL Cache:** 1,800 seconds (30 minutes); maximum response payload limit 512 KB.
- **Localization Fallback:** `_no_idioma(aviso, lang)` extracts translated strings matching the application's current UI language (`pt`, `en`, `es`, `fr`, `de`, `tr`), defaulting to Portuguese or English.
- **Read State Tracking:** Read notice IDs are saved in `fmsh_settings.json` under `avisos_lidos` (capped at the 200 most recent items to avoid unbounded configuration growth).

### 6.2 Supporter Credit Lists (`apoiadores.pyc`)

- **Service Endpoint:** `https://fmsh-acesso.marcellofelipe90.workers.dev/apoiadores?nivel=NIVEL_CREDITOS`
- **Local Storage:** `paths.local_data_path('fmsh_apoiadores.json')`
- **TTL Cache:** 21,600 seconds (6 hours); payload limit 512 KB.
- **Network Resilience:** Uses stale cache data if network requests fail; empty list fallback if no cache exists.

### 6.3 Dynamic Offsets Architecture (`offsets.pyc` & `offsets_embutidos.pyd`)

- **Storage Location:** Compiled directly into `offsets_embutidos.cp314-win_amd64.pyd` as a compressed zlib binary payload at byte offset `0x25a06` (uncompressed JSON size: 60,837 bytes).
- **Structure:**
  ```json
  {
    "ASSINATURAS": {
      "schema_version": 1,
      "base_module": "game_plugin.dll",
      "versions": {
        "26.3.2+2329565": { ... },
        "24.4.2+2081827": { ... }
      }
    },
    "TRACOS": { ... }
  }
  ```
- **Fallback / Override Protocol:** If `offsets_embutidos` cannot be imported or needs external overriding, `offsets._ler()` searches `resource_path('signatures', 'signatures.json')`. This allows developers to distribute updated offset JSON files to users without recompiling application binaries.

---

## 7. Diagnostics Subsystem (`FMSH-Diagnostico.exe` & `diagnostico_core.pyd`)

### 7.1 Architecture & Separation of Concerns

The diagnostics system is decoupled into:
1. `diagnostico_core.cp314-win_amd64.pyd`: The pure metric collection engine. Accepts a `Relatorio` collector object and writes diagnostic data without performing direct stdout printing or UI operations.
2. `diagnostico_app.pyc` (`FMSH-Diagnostico.exe`): Standalone console launcher using `Relatorio(eco=True)` to stream results to terminal.
3. `/api/diagnostico`: Integrated local REST endpoint invoked by the main GUI settings page.

### 7.2 Diagnostic Inspection Inventory

The tool runs 7 structured inspection blocks:

```
+--------------------------------------------------------------------------------+
|                         FMSH Diagnostic Execution Blocks                       |
+--------------------------------------------------------------------------------+
| 1. AMBIENTE (Environment)                                                      |
|    - Windows OS Version, Build, UBR, and Architecture (32/64 bit).             |
|    - Microsoft Edge WebView2 Runtime registry installation and version.        |
|    - Active Antivirus software inventory via Windows Security Center (WMI).    |
|    - File execution context: Detects running from Temp / unextracted archive.  |
|    - Mark of the Web: Queries NTFS Alternate Data Stream Zone.Identifier.      |
|    - Registry MIME mapping: Validates HKCR\.js\Content Type == application/js  |
|      (Detects corrupt legacy registry keys where .js was set to text/plain).   |
+--------------------------------------------------------------------------------+
| 2. PROCESSOS DO FOOTBALL MANAGER (Process Checks)                              |
|    - Scans for running fm.exe processes.                                       |
|    - Multi-process warning: Flags if multiple FM instances are running.        |
|    - Process Elevation Check: Calls OpenProcessToken & GetTokenInformation     |
|      (TokenElevation) on fm.exe to test if game runs as Administrator while    |
|      FMSH runs non-elevated (a primary cause of memory read access denial).    |
+--------------------------------------------------------------------------------+
| 3. LEITURA DA MEMORIA (Memory Reading Validation)                              |
|    - Attempts OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION).        |
|    - Detects target binary: game_plugin.dll (FM26) vs fm.exe (FM24).           |
|    - ProductVersion extraction from PE version resources (e.g. 26.3.2+2329565).|
|    - Store Platform Detection: Steam vs Epic Games Store vs Xbox Game Pass.    |
|      Warns that FM24 on non-Steam stores lacks mapped memory offsets.          |
|    - Base address resolution and heap window boundary validation.              |
+--------------------------------------------------------------------------------+
| 4. O QUE O APP CONSEGUE LER (Data Sanity Checks)                               |
|    - Reads raw in-game date structure; compares against formatted game date.   |
|    - Validates active save game identifier and root container pointers.        |
+--------------------------------------------------------------------------------+
| 5. VEREDITO (Automated Diagnosis & Actionable Advice)                          |
|    - Matches collected errors against known operational fault patterns.        |
+--------------------------------------------------------------------------------+
| 6. ULTIMAS LINHAS DO LOG DO APP (Log Tail)                                     |
|    - Ingests trailing 50 lines from fmsh.log.                                  |
+--------------------------------------------------------------------------------+
| 7. REDE (Network Reachability Check)                                           |
|    - Probes https://fmsh-acesso.marcellofelipe90.workers.dev/avisos.           |
|    - Measures HTTP response code and round-trip latency in seconds.            |
|    - Clarifies to user: Memory reading does NOT need network; connectivity is  |
|      strictly required for initial key activation and announcements.           |
+--------------------------------------------------------------------------------+
```

### 7.3 Diagnostic Artifact Output

Reports are generated and saved to:
`%USERPROFILE%\Documents\FM Season Hub\diagnostic\diagnostico-%Y%m%d-%H%M%S.txt`
Language preference is automatically synchronized with `fmsh_settings.json` (`idioma_gravado()`).

---

## 8. Inno Setup Configuration, Registry, & File System Footprint

### 8.1 Installer Metadata & Identity

- **Compiler Engine:** Inno Setup 6.7.0 (Unicode)
- **Application Name:** FM Season Hub
- **Application Version:** `0.8.2.1`
- **Application ID GUID:** `{7081324C-BDD5-4E77-B3D1-05C7DEDBC360}`
- **Default Installation Directory:** `%ProgramFiles%\FM Season Hub`
- **Supported Languages:** `pt` (Português Brasileiro), `en` (English), `es` (Español), `fr` (Français), `de` (Deutsch), `tr` (Türkçe).

### 8.2 File System Layout

```
%ProgramFiles%\FM Season Hub\
├── FMSH.exe                          (Main application launcher, PyInstaller/Nuitka bootloader)
├── FMSH-Diagnostico.exe              (Standalone diagnostics CLI utility)
├── unins000.exe                      (Inno Setup uninstaller binary)
├── unins000.dat                      (Uninstall state database)
├── plugins.ini                       (Registry of installed BepInEx plugins and target game paths)
└── _internal\                        (Runtime dependencies & compiled C extensions)
    ├── python314.dll
    ├── libcrypto-3.dll
    ├── libssl-3.dll
    ├── sqlite3.dll
    ├── acesso.cp314-win_amd64.pyd
    ├── assinatura.cp314-win_amd64.pyd
    ├── atualizacao.cp314-win_amd64.pyd
    ├── plugins_atualizador.cp314-win_amd64.pyd
    ├── diagnostico_core.cp314-win_amd64.pyd
    ├── offsets_embutidos.cp314-win_amd64.pyd
    ├── server.cp314-win_amd64.pyd
    └── webview\

%LOCALAPPDATA% / Installation Folder \dados\  (Paths logic in paths.py):
├── fm26_snapshots.db                 (SQLite database storing career data and player captures)
├── fmsh_settings.json                (Application configuration, auth state, UI preferences)
├── fmsh_avisos.json                  (Cached announcements)
├── fmsh_apoiadores.json              (Cached supporter roster)
├── fmsh_versao.json                  (Cached update manifest)
└── fmsh.log                          (Application runtime event log)

%USERPROFILE%\Documents\FM Season Hub\
├── diagnostic\                       (Automated diagnostics output directory)
└── alpha\                            (Development mode data root fallback)
```

### 8.3 Registry Keys

1. **Uninstaller Registration:**
   `HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\Uninstall\{7081324C-BDD5-4E77-B3D1-05C7DEDBC360}_is1`
   - `DisplayName`: `"FM Season Hub"`
   - `DisplayVersion`: `"0.8.2.1"`
   - `InstallLocation`: Path to main application directory.
   - `UninstallString`: Path to `unins000.exe`.
   - `QuietUninstallString`: Path to `unins000.exe /SILENT`.

2. **System Queries (Read-Only):**
   - `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography` -> `MachineGuid` (Hardware hash).
   - `HKEY_CLASSES_ROOT\.js` -> `Content Type` (Verified during diagnostics).
   - `HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` -> `pv` (WebView2 version).

### 8.4 Legal Acceptance Handshake (`legal.pyd`)

1. During installation, the Inno Setup wizard displays `TERMOS.txt` and `PRIVACIDADE.txt` (or English equivalents `TERMOS.en.txt`, `PRIVACIDADE.en.txt`).
2. When the user accepts, the installer writes a temporary acceptance record.
3. Upon first launch of `FMSH.exe`, `legal.migrar_aceite_do_instalador()` reads the record, validates that both Terms and Privacy notices match the current version, commits the agreement state to `fmsh_settings.json`, and securely deletes the temporary installer file.

---

## 9. Comprehensive Architectural Assessment

1. **Security Posture:**
   The client-server protocol exhibits strong architectural separation. Executable downloads (updates and plugins) are protected by RSA PKCS#1 v1.5 digital signatures and SHA-256 verification. Compromise of third-party CDNs or GitHub hosting cannot lead to arbitrary code execution without the developer's private key.
2. **Privacy Guarantees:**
   Telemetry is deliberately minimized. Plugin update checks send only installed IDs (`id@versao`); machine hashes are one-way SHA-256 digests; update requests route through a Cloudflare Worker proxy to protect user IP addresses from direct GitHub logging.
3. **Robustness & Offline Tolerance:**
   All network failures are handled gracefully without application crashes. Core features, data viewing, and memory analysis operate entirely offline without requiring network heartbeat checks.
