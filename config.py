import base64
from os import environ
from dotenv import load_dotenv
from configparser import ConfigParser

load_dotenv()
config = ConfigParser()

DEPLOY = bool(environ.get('DEPLOY'))
CONFIG_FILE = str(environ.get('CONFIG_FILE', 'config.ini'))


def get_env(name: str, fallback: str = "") -> str:
    """Return an (optionally base64-encoded) env var."""
    variable = environ.get(name)
    if DEPLOY and variable is not None:
        variable = base64.b64decode(variable).decode()
    return variable or fallback


class Config:
    @staticmethod
    def set_conf(config_path: str):
        config.read(config_path)

    @staticmethod
    def get_conf_key(section, key, fallback=None, value_type='str'):
        value = fallback
        if config.has_section(section):
            if value_type == 'str':
                value = config.get(section, key, fallback=fallback)
            elif value_type == 'bool':
                value = config.getboolean(section, key, fallback=fallback)
            elif value_type == 'int':
                value = config.getint(section, key, fallback=fallback)
            elif value_type == 'float':
                value = config.getfloat(section, key, fallback=fallback)
            else:
                raise TypeError(f'Given type: {value_type} is not defined.')

        return value

    @staticmethod
    def set_conf_key(section, key, value):
        if config.has_section(section):
            config.set(section, key, value)


class PostgreSQL:
    PGHOST = get_env("PGHOST")
    PGPORT = get_env("PGPORT")
    PGUSER = get_env("PGUSER")
    PGDATABASE = get_env("PGDATABASE")
    PGPASSWORD = get_env("PGPASSWORD")
    DB_URL = get_env('DATABASE_URL')

    @classmethod
    def return_connection_str(cls):
        if cls.DB_URL is not "":
            return cls.DB_URL

        return f"postgres://{cls.PGUSER}:{cls.PGPASSWORD}@{cls.PGHOST}:{cls.PGPORT}/{cls.PGDATABASE}"


# read config file
Config.set_conf(CONFIG_FILE)

BOT_TOKEN = get_env("BOT_TOKEN")
CLIENT_ID = get_env("CLIENT_ID")
SENTRY_URL = get_env("SENTRY_URL")

# ***** guild and channel settings *******
GUILD_ID = int(environ.get("GUILD_ID", Config.get_conf_key('channels', "GUILD_ID", "648262260724203523")))
LOGGING_CHANNEL_ID = int(
    environ.get("LOGGING_CHANNEL_ID", Config.get_conf_key('channels', "LOGGING_CHANNEL_ID", "648867664026009621")))
ANNOUNCEMENT_CHANNEL_ID = int(
    environ.get("ANNOUNCEMENT_CHANNEL_ID", Config.get_conf_key('channels', "ANNOUNCEMENT_CHANNEL_ID", "653301549979795467")))
CONFESSION_CHANNEL_ID = int(
    environ.get("CONFESSION_CHANNEL_ID", Config.get_conf_key('channels', "CONFESSION_CHANNEL_ID", "750452002248458330")))
RECEPTION_CHANNEL_ID = int(
    environ.get("RECEPTION_CHANNEL_ID", Config.get_conf_key('channels', "RECEPTION_CHANNEL_ID", "648623592828960768")))
ADMIN_CHANNEL_ID = int(
    environ.get("ADMIN_CHANNEL_ID", Config.get_conf_key('channels', "ADMIN_CHANNEL_ID", "653695277605322761")))

# ****** people **********
OWNER_ID = int(environ.get("OWNER_ID", Config.get_conf_key('members', "OWNER_ID", "647577161200566289")))

# ##### admin cog constants #######
# ***** roles ***********
# role given for newcomers who not approved and waiting in a reception
STRANGER_ROLE_NAME = 'Yabancılar'
# role given for members with top statistics
LEADER_ROLE_NAME = 'Lider'
# valid roles (higher is better)
BOT_ROLE_NAME = 'Bot'
TIER1 = 'Çaylaklar'
TIER2 = 'Tecrübeliler'
TIER3 = 'Müdavimler'
TIER4 = 'Yönetim'
TIER5 = 'Sahip'
# role that activity rule will be determined
ACTIVITY_ROLE_NAME = 'Aktif'
ADMIN_ROLE_NAMES = (TIER5, TIER4)
GENDER_ROLE_NAMES = ('Hanimefendi', 'Beyefendi', 'LGBT+')
# roles that activity rule will effect
ACTIVITY_INCLUDED_ROLES = (TIER2, TIER1)
# roles use for getting stats
STATS_ROLES = (TIER5, TIER4, TIER3, TIER2, TIER1, BOT_ROLE_NAME, STRANGER_ROLE_NAME)
VALID_STATS_ROLES = (TIER5, TIER4, TIER3, TIER2, TIER1)
# roles for using user command (getting number of days to upgrade next role)
ROLE_HIERARCHY = {TIER1: (TIER2, 60), TIER2: (TIER3, 240)}
# ***** constants ********
# minimum number of needed days removing inactive members after last prune
activity_schedule_gap = '5d'
# minimum number of days passed since a member joined to be effected by activity removal rule
activity_min_day = 7
# text template for activity announcement
activity_template = '{} tarihine kadar aktiflik sartini saglamaz veya yonetime mazeret ' \
                    'bildirmez ise cikartilacak uye listesi'
# text template for activity announcement in pm channel
activity_pm_template = 'Bu mesajı sana {} dan gönderiyorum.' \
                       'Artık seni aramızda sık sık göremiyoruz ve bu bizi çok üzüyor 😔 . ' \
                       'Aktiflik rolüne sahip olmadığın için seni atılacak üye listesine ekledik. ' \
                       'Eğer {} tarihine kadar aktif rolünü kazanmazsan veya yönetime eksikliğinin ' \
                       'mazeretini bildirmez isen maalesef seni yukarıdaki tarihte kanaldan atmak zorunda kalacağım 😢 .'
# text template to send removed members to rejoin if they would like to
removed_member_pm_template = 'Tekrar merhaba! Aktiflik rolünü daha önce belirtilen tarihe kadar ' \
                             'kazanamadığın için {} sunucusundan çıkartıldın. Ama bu herşeyin sonu demek değil. ' \
                             'Senin için yeni bir davet oluşturdum, işte burda: {} \n Bu davet linki ile istersen ' \
                             'bize tekrar katılabilirsin, unutma bu davet sadece {} gün geçerli olacak. ' \
                             'Davete tıklayıp yeniden kanala katıldığında bu sefer aktif olacağına ' \
                             'dair bana söz vermiş olacaksın, unutma!!!'

# role upgrade template
role_upgrade_template = 'Tebrikler {}! {} rolunden {} rolune yukseldin!'
# number of days for checking role upgrade
role_upgrade_gap = '1d'
# minimum number of days for role transitions
TIER1toTIER2 = 60
TIER2toTIER3 = 240
# directory for json permission templates
base_json_dir = 'json_templates'

# various delay value for operations such as message deletion
short_delay = Config.get_conf_key('main', "short_delay", 60, value_type='int')
mid_delay = Config.get_conf_key('main', "mid_delay", 120, value_type='int')
long_delay = Config.get_conf_key('main', "long_delay", 300, value_type='int')
##### Confession cog #########
message_timeout = Config.get_conf_key('confession', "message_timeout", 600, value_type='int')
warn_limit = Config.get_conf_key('confession', "warn_limit", 3, value_type='int')
command_cooldown = Config.get_conf_key('confession', "command_cooldown", 6000, value_type='int')
##############################
##### Fun ####################
TENOR_API_KEY = get_env("TENOR_API_KEY")
##### Cameradice #############
max_lost_member = Config.get_conf_key('cameradice', "max_lost_member", 4, value_type='int')
start_game_delay = Config.get_conf_key('cameradice', "start_game_delay", 10, value_type='int')
##############################
##### Automation cog #########
# number of days the inactive members will be announced in announcement channel
num_announce_days = Config.get_conf_key('announcement', "num_announce_days", 2, value_type='int')
announcement_template = 'Maalesef aşağıda listelenen üyelerimiz kanalın aktiflik şartını sağlayamadıkları ' \
                        'için **{}** rolüne sahip değiller. **{}** rolüne sahip olmayan bu üyeler olası bir aktif ' \
                        'olmayan üyeleri çıkarma işleminde kanaldan **ATILACAKLARDIR!!!** Bu üyelerden ricamız ' \
                        'lütfen en kısa sürede kanalda yeterince aktif olmaya başlamalarıdır.\n' \
                        '** *Aşağıda mazeretlerini bildiren üyeler listelenmiştir, ' \
                        'lütfen bu üyeler duyuruyu dikkate almasın. ' \
                        'Bu üyeler haricinde eğer geçici bir mazeretiniz varsa lütfen yönetime bildirin.* ** \n' \
                        '***Aktiflik şartı: https://sites.google.com/view/nightzone/ana-sayfa#h.p_6i1CL4wFpmQV***\n'
##############################
# Emoji Alphabet
EMOJI_LETTERS = [
    "\U0001f1e6\U0001f170\U0001F359",  # A
    "\U0001f1e7\U0001f171",  # B
    "\U0001f1e8\u262a\u00A9",  # C
    "\U0001f1e9\u21a9",  # D
    "\U0001f1ea\U0001f4e7",  # E
    "\U0001f1eb",  # F
    "\U0001f1ec\u26fd",  # G
    "\U0001f1ed\u2653",  # H
    "\U0001f1ee\u2139",  # I
    "\U0001f1ef\u2614",  # J
    "\U0001f1f0",  # K
    "\U0001f1f1\U0001f552\U0001F462",  # L
    "\U0001f1f2\u24c2\u24c2\u264f\u264d\u303d",  # M
    "\U0001f1f3\U0001f4c8\U0001F3B5",  # N
    "\U0001f1f4\U0001f17e\u2b55",  # O
    "\U0001f1f5\U0001f17f",  # P
    "\U0001f1f6",  # Q
    "\U0001f1f7",  # R
    "\U0001f1f8\U0001f4b0\u26a1\U0001F4B2",  # S
    "\U0001f1f9\u271d\U0001F334",  # T
    "\U0001f1fa\u26ce",  # U
    "\U0001f1fb\u2648",  # V
    "\U0001f1fc\u3030",  # W
    "\U0001f1fd\u274e\u274c\u2716",  # X
    "\U0001f1fe\U0001f331\u270C",  # Y
    "\U0001f1ff\U0001f4a4",  # Z
    "\u26ab\U0001f535\U0001f534\u26aa",  # Whitespace alternatives
    "\u2755\u2757\u2763",  # !
    "\u2754\u2753",  # ?
    "\U0001f4b2",  # $
    "\U000021aa",  # (
    "\U000021a9"  # )
]
