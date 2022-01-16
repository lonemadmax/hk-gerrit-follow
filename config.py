import configparser


__all__ = ('config')


ini = configparser.ConfigParser()
with open('config.ini', 'rt') as f:
    ini.read_file(f)
config = dict(ini['Builder'])

AUTH = None
try:
    user = config['user']
    password = config['password']
    if user and password:
        AUTH = (user, password)
except KeyError:
    pass
config['AUTH'] = AUTH

for name in ('gerrit_cache', 'max_jobs', 'time_limit', 'low_disk'):
    config[name] = int(config[name])

for name in ('keep_done_pressure', 'keep_done'):
    config[name] = float(config[name])

for name in ('archive_src',):
    config[name] = ini['Builder'].getboolean(name)

config['arches'] = {}
for name in ini.sections():
    if name == 'Builder':
        continue
    if not ini[name].getboolean('active'):
        continue
    job = dict(ini[name])
    for optname in ('save_artifacts',):
        job[optname] = ini[name].getboolean(optname)
    # TODO: quoted spaces
    job['jam_options'] = job['jam_options'].split()
    config['arches'][job['arch']] = job

del ini, name, optname, job

