import configparser


__all__ = ('config')


config = configparser.ConfigParser()
with open('config.ini', 'rt') as f:
    config.read_file(f)
config = dict(config['DEFAULT'])

AUTH = None
try:
    user = config['user']
    password = config['password']
    if user and password:
        AUTH = (user, password)
except KeyError:
    pass
config['AUTH'] = AUTH

