import configparser


__all__ = ('AUTH', 'config')


config = configparser.ConfigParser()
with open('config.ini', 'rt') as f:
    config.read_file(f)

AUTH = None
try:
    user = config.get('DEFAULT', 'user')
    password = config.get('DEFAULT', 'password')
    if user and password:
        AUTH = (user, password)
except Exception:
    pass

