from urllib.parse import urlsplit

DOMINIOS_PERMITIDOS = (
    'patreon.com',
    'discord.gg',
    'discord.com',
    'x.com',
    'github.com',
    'notion.site',
    'workers.dev',
    'instant-gaming.com',
)


def host_permitido(host):
    host = (host or '').lower().strip('.')
    host = host.split(':')[0]
    for d in DOMINIOS_PERMITIDOS:
        if host == d or host.endswith('.' + d):
            return True
    return False


def conferir(url):
    if not url or not isinstance(url, str):
        return False, 'endereco vazio'
    if len(url) > 2000:
        return False, 'endereco longo demais'
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return False, 'endereco ilegivel'
    if p.scheme != 'https':
        return False, 'so https e aceito (veio %r)' % (p.scheme or 'nada')
    if not p.hostname:
        return False, 'endereco sem dominio'
    if not host_permitido(p.hostname):
        return False, 'dominio fora da lista: %s' % p.hostname
    return True, ''
