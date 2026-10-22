VERSION = '0.8.2.1'
CANAL = ''


def rotulo():
    if CANAL:
        return (VERSION + ' ' + CANAL).strip()
    return VERSION
