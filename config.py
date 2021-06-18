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

config['ARCHES'] = config['arches'].split()

for name in ('gerrit_cache', 'max_jobs', 'time_limit', 'low_disk'):
    config[name] = int(config[name])

for name in ('keep_done_pressure', 'keep_done'):
    config[name] = float(config[name])

for name in ('archive_src',):
    config[name] = config[name].lower() in ('true', 'yes', '1', 'on')
