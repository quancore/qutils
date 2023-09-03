import base64
from os import environ, path, replace
from dotenv import load_dotenv
from configparser import ConfigParser
import typing
import asyncio
from benedict import benedict
from ruyaml import YAML, error as yaml_error
import yamale
import uuid


load_dotenv()
# a converter to read lists
# config = ConfigParser(converters={'list': lambda x: [i.strip() for i in x.split(',')]})

# DEPLOY = bool(environ.get('DEPLOY'))

# YAML config file path
#CONFIG_FILE_PATH = ",/configs/config.yaml"
CONFIG_FILE_PATH = ",/configs/test_config.yaml"
# a template file use for validating YAML config file
SCHEMA_FILE_PATH = "schema.yaml"

# default prefix for guilds
base_prefixes = ['?', '!']

# default bot settings
default_bot_settings = benedict({
    "logger_name": "Qutils",
    "log_level": "DEBUG"
})

# default_cog_config
default_cog_config = benedict({
    "short_delay": 87,
    "mid_delay": 120,
    "long_delay": 300,
    "general": {
        "activity_schedule_gap": "5d",
        "role_upgrade_gap": "1d",
        "activity_min_day": 7,
        "base_json_dir": "json_templates",
        "activity_template": "Here is the members will be discarded"
                             "if they do not get active role until {}",
        "activity_pm_template": "The PM has been sent by {}.\n"
                                "We have added you the member dischargement list"
                                "because of your inactivity in our server."
                                "If you will not get the active role until {}, you will be banished from server.",
        "removed_member_pm_template": "You have been banished from {} because of your inactivity."
                                      "Here is the invite to rejoin our server: {}",
        "role_upgrade_template": "Congrats {}, your role have been upgraded to {}!"
    },
    "confession": {
        "message_timeout": 600,
        "warn_limit": 3,
        "command_cooldown": 6000
    },
    "camdice": {
        "max_lost_member": 4,
        "start_game_delay": 2
    },
    "truthdare": {
        "base_truthdare_dir": "truthdare"
    },
    "automation": {
        "num_announce_days": 2,
        "announcement_template": "Here is the inactive members do not have the role of {}\n"
                                 "The members not have {} will be banished from server."
    }
})


class Singleton (type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class PostgreSQL(metaclass=Singleton):
    """
    Discord bot database credentials.
    This class intended to be read only.
    """
    __RAW_CONFIG: benedict = None
    __PGHOST: str = ""
    __PGPORT: str = ""
    __PGDATABASE: str = ""
    __PGUSER: str = ""
    __PGPASSWORD: str = ""
    __DB_URL: str = ""

    def __init__(self, db_conf: benedict):
        self.initialize_vars(db_conf)

    @classmethod
    def initialize_vars(cls, db_conf: benedict):
        """ Initialize or update class attributes """
        if cls.__RAW_CONFIG is None or (cls.__RAW_CONFIG and cls.__RAW_CONFIG != db_conf):
            cls.__RAW_CONFIG = db_conf
            cls.__PGHOST = db_conf.get_str("PGHOST", "") or Config.get_env("PGHOST")
            cls.__PGPORT = db_conf.get_str("PGPORT", "") or Config.get_env("PGPORT")
            cls.__PGDATABASE = db_conf.get_str("PGDATABASE", "") or Config.get_env("PGDATABASE")
            cls.__PGUSER = db_conf.get_str("PGUSER", "") or Config.get_env("PGUSER")
            cls.__PGPASSWORD = db_conf.get_str("PGPASSWORD", "") or Config.get_env("PGPASSWORD")
            cls.__DB_URL = db_conf.get_str("DB_URL", "") or Config.get_env("DATABASE_URL")

    @property
    def db_conf(self) -> benedict:
        """ Get raw postgres connection credentials """
        return PostgreSQL.__RAW_CONFIG

    @property
    def host(self) -> str:
        """ Get postgres host info """
        return PostgreSQL.__PGHOST

    @property
    def database(self) -> str:
        """ Get postgres database info """
        return PostgreSQL.__PGDATABASE

    @property
    def user(self) -> str:
        """ Get postgres user info """
        return PostgreSQL.__PGUSER

    @property
    def password(self) -> str:
        """ Get postgres password info """
        return PostgreSQL.__PGPASSWORD

    @property
    def db_url(self) -> str:
        """ Get postgres database url if exist """
        return PostgreSQL.__DB_URL

    @classmethod
    def get_conn_str(cls):
        """ Return Postgres connection string """
        if cls.__DB_URL is not "":
            return cls.__DB_URL

        return f"postgres://{cls.__PGUSER}:{cls.__PGPASSWORD}@{cls.__PGHOST}:{cls.__PGPORT}/{cls.__PGDATABASE}"


class Auth(metaclass=Singleton):
    """
    Discord bot tokens and various authorization credentials
    This class intended to be read only.
    """
    __RAW_CONFIG: benedict = None
    # Discord bot token
    __BOT_TOKEN: str = ""
    # Discord bot Client ID
    __CLIENT_ID: str = ""

    def __init__(self, auth_conf: benedict):
        self.initialize_vars(auth_conf)

    @classmethod
    def initialize_vars(cls, auth_conf: benedict):
        """ Initialize or update class attributes """
        if cls.__RAW_CONFIG is None or (cls.__RAW_CONFIG and cls.__RAW_CONFIG != auth_conf):
            cls.__RAW_CONFIG = auth_conf
            cls.__BOT_TOKEN = auth_conf.get_str("BOT_TOKEN", "")
            cls.__CLIENT_ID = auth_conf.get_str("CLIENT_ID", "")

    @property
    def token(self) -> str:
        """ Get token of the bot """
        return Auth.__BOT_TOKEN

    @property
    def client_id(self) -> str:
        """ Get client id of the bot """
        return Auth.__CLIENT_ID

    @property
    def auth_conf(self) -> benedict:
        """ Get raw settings of bot auth """
        return Auth.__RAW_CONFIG

    @classmethod
    def get(cls, var: str, fallback: typing.Any) -> typing.Any:
        """ Get a value with given key """
        assert cls.__RAW_CONFIG
        return cls.__RAW_CONFIG.get(var, fallback)


class Guild:
    __SEPARATOR: str = "."  # keypath separator for benedict

    """ Guild config represent various config on server level """
    def __init__(self, guild_conf: benedict, separator: str = "."):
        self.__raw_config = guild_conf
        Guild.__SEPARATOR = separator
        guild_id = guild_conf.get_int("ID", None)
        if guild_id is None:
            raise ValueError("Guild ID is not given in configuration")

    @property
    def id(self) -> typing.Optional[int]:
        """ Get id the guild """
        return self.__raw_config.get_int("ID", None)

    @property
    def prefix(self) -> typing.Optional[list]:
        """ Get prefix list of the guild """
        return self.__raw_config.get_list("PREFIX", base_prefixes)

    @property
    def separator(self) -> str:
        """ Get keypath seperator for python benedict class """
        return Guild.__SEPARATOR

    @property
    def guild_conf(self) -> benedict:
        """ Get raw guild settings """
        return self.__raw_config

    def get_channels(self, fallback: typing.Any) -> typing.Optional[benedict]:
        """ Get channel settings for the guild """
        return self.__raw_config.get("channels", fallback)

    def get_helper_roles(self, fallback: typing.Any) -> typing.Optional[benedict]:
        """ Get helper roles settings for the guild """
        return self.__raw_config.get(f"roles{Guild.__SEPARATOR}HELPER_ROLES", fallback)

    def get_hierarchy_roles(self, fallback: typing.Any) -> typing.Optional[benedict]:
        """ Get hierarchy roles settings for the guild """
        return self.__raw_config.get(f"roles{Guild.__SEPARATOR}HIERARCHY_ROLES", fallback)

    def get_gender_roles(self, fallback: typing.Any) -> typing.Optional[list]:
        """ Get gender roles settings for the guild """
        return self.__raw_config.get(f"roles{Guild.__SEPARATOR}GENDER_ROLES", fallback)

    def get_cog(self, cog_name: str, fallback: typing.Any = None) -> typing.Optional[benedict]:
        """ Get a cog for a guild.
        If no settings, it first check default config then
        if None return fallback. """
        val = self.__raw_config.get(f"cogs{Guild.__SEPARATOR}{cog_name}", None)
        if val is None:
            default_val = default_cog_config.get(cog_name)
            val = default_val or fallback

        return val

    @staticmethod
    def _find_key(search_dict: benedict, key: str, fallback: typing.Any) -> typing.Any:
        """
        Search a key in a benedict and return res.
        :param search_dict: Benedict to be searched.
        :param key: Key to be searched.
        :return: Found value or fallback
        """
        res = None
        p_res = search_dict.search(key, in_keys=True, in_values=False, exact=True, case_sensitive=True)
        if p_res:
            for r in p_res[0]:
                if isinstance(r, (benedict, dict)) and r.get(key) is not None:
                    res = r.get(key)

        return res or fallback

    def find_cog_setting(self, cog_setting_name: str,
                         fallback: typing.Any = None) \
            -> typing.Optional[typing.Any]:
        """
        Find a given setting by key name in cogs.
        """
        res = None
        cogs = self.__raw_config.get(f"cogs", None)
        if cogs:
            res = Guild._find_key(cogs, cog_setting_name, None)

        if res is None:
            res = res or Guild._find_key(default_cog_config, cog_setting_name, None)

        return res or fallback

    def get(self, var: str, fallback: typing.Any) -> typing.Any:
        """ Get a value with given key """
        assert self.__raw_config
        return self.__raw_config.get(var, fallback)

    def put(self, key: typing.Union[str, int, float], value: typing.Any):
        """ Put a value with given key and value pair """
        assert self.__raw_config
        self.__raw_config[key] = value


class Config(metaclass=Singleton):
    __CONFIG_FILE_PATH: typing.Optional[str] = None
    __SCHEMA_FILE_PATH: typing.Optional[str] = None  # a schema file to validate YAML file
    __YAML_HANDLER: typing.Optional[YAML] = None  # yaml handler instance

    __RAW_CONFIG: typing.Optional[benedict] = None
    __AUTH_CONFIG: typing.Optional[Auth] = None  # read-only
    __DB_CONFIG: typing.Optional[PostgreSQL] = None  # read-only
    __API_CONFIG: typing.Optional[benedict] = None  # read-only
    __BOT_SETTINGS: typing.Optional[benedict] = None
    __GUILDS_CONFIG: typing.Optional[typing.Dict[int, Guild]] = None

    __LOOP: asyncio.BaseEventLoop
    __LOCK: asyncio.Lock = asyncio.Lock()
    __SEPARATOR: str = "."  # keypath separator for benedict

    def __init__(self, **options):
        """Init class for Config.

        :keyword options: Various keyword option for Config class.

        - str **config_file_path** : YAML config file (default is None), if not given, the value is read from environment.
        - str **schema_file_path** : A schema YAML file to validate Config YAML (default is None),
          if not given, the value is read from environment. If not found, no validation will be occurred.
        - eventloop **loop** : An event loop to handle async operations like save etc. (default is None),
          if not given, the value is read from environment. If not found, no validation will be occurred.
        - str **separator**: Python benedict library keypath seperator (default: ".")

        :return: None
        """
        # Get YAML config file path
        Config.__CONFIG_FILE_PATH = options.pop('config_file_path', Config.get_env("CONFIG_FILE_PATH", None))

        # Check that specified config file exists
        assert path.exists(Config.__CONFIG_FILE_PATH)

        # get asyncio event loop
        Config.__LOOP = options.pop('loop', asyncio.get_event_loop())

        # get keypath separator for benedict
        Config.__SEPARATOR = options.pop('separator', ".")

        # validate yaml file before use it with template
        Config.__SCHEMA_FILE_PATH = options.pop('schema_file_path', Config.get_env("SCHEMA_FILE_PATH", None))
        if Config.__SCHEMA_FILE_PATH is not None:
            # Check that specified config file exists
            assert path.exists(Config.__SCHEMA_FILE_PATH)
            self.validate()

        # Setup YAML handler
        Config.__YAML_HANDLER = YAML()

        # read config from YAML file
        Config.load_from_file()

    # ### Class based utils methods ####
    @staticmethod
    def get_config_path() -> str:
        """Get yaml config path.
        :return: config path.
        """
        return Config.__CONFIG_FILE_PATH

    @staticmethod
    def get_env(name: str, fallback: typing.Optional[str] = None) -> typing.Optional[str]:
        """Get an env var.
        :param name: Name of env. var.
        :param fallback: Any fallback value if not found.
        :return: Env var. value
        """

        return environ.get(name) or fallback

    # #### YAML related methods ####
    @classmethod
    def validate(cls):
        """ Validate config YAML file against template file """
        try:
            schema = yamale.make_schema(path=cls.__SCHEMA_FILE_PATH, parser='ruamel')
            data = yamale.make_data(path=cls.__CONFIG_FILE_PATH, parser='ruamel')
            yamale.validate(schema, data, strict=False)
            print('Validation success! 👍')
        except yamale.YamaleError as e:
            print('Validation failed!\n')
            for result in e.results:
                print("Error validating data '%s' with '%s'\n\t" % (result.data, result.schema))
                for error in result.errors:
                    print('\t%s' % error)
            exit(1)
        except ValueError as e:
            print('YAML validation failed!\n%s' % str(e))
            exit(1)

    @classmethod
    def initialize_vars(cls):
        """ Initialize or update class variables """
        if cls.__RAW_CONFIG:
            # initialize db config
            cls.__DB_CONFIG = PostgreSQL(cls.__RAW_CONFIG.get("db"))
            # initialize auth config for bot
            cls.__AUTH_CONFIG = Auth(cls.__RAW_CONFIG.get("auth"))
            # initialize api config
            cls.__API_CONFIG = cls.__RAW_CONFIG.get("api_keys")
            # initialize general bot settings like owner id etc.
            cls.__BOT_SETTINGS = cls.__RAW_CONFIG.get("bot_settings")
            # initialize guild confs using Guild class
            if cls.__RAW_CONFIG.get("guilds") is not None:
                guild_class_confs = {}
                for guild_conf in cls.__RAW_CONFIG.get("guilds"):
                    guild_conf = benedict(guild_conf, keypath_separator=cls.__SEPARATOR)
                    if guild_conf.get_int("ID", None) is not None:
                        guild_class_confs[guild_conf.get_int("ID")] = Guild(guild_conf, separator=cls.__SEPARATOR)

                cls.__GUILDS_CONFIG = guild_class_confs
        else:
            raise ValueError(f"Config dict is None or empty.\n{cls.__RAW_CONFIG}")

    @classmethod
    def load_from_file(cls):
        """ Read YAML file and store the config and related subpart """
        try:
            with open(cls.__CONFIG_FILE_PATH, 'r') as stream:
                raw_config_dict = cls.__YAML_HANDLER.load(stream)

            cls.__RAW_CONFIG = benedict(raw_config_dict, keypath_separator=cls.__SEPARATOR)
            # cls.__RAW_CONFIG = benedict.from_yaml(cls.__CONFIG_FILE_PATH)

        except (ValueError, yaml_error.YAMLError) as exc:
            print(f"Error reading and processing config file: {cls.__CONFIG_FILE_PATH}\n{exc}")
        else:
            # initialize all related class configs and instances
            cls.initialize_vars()

    @classmethod
    async def load(cls):
        """ Thread-safe async load method """
        async with cls.__LOCK:
            await cls.__LOOP.run_in_executor(None, cls.load_from_file)

    @classmethod
    def _dump(cls):
        """ Dump dict to YAML format """
        temp = '%s-%s.tmp' % (uuid.uuid4(), cls.__CONFIG_FILE_PATH)
        with open(temp, 'w', encoding='utf-8') as tmp:
            cls.__YAML_HANDLER.default_flow_style = False
            cls.__YAML_HANDLER.dump(cls.__RAW_CONFIG.copy(), tmp)

        # atomically move the file
        replace(temp, cls.__CONFIG_FILE_PATH)

    @classmethod
    async def save(cls):
        async with cls.__LOCK:
            await cls.__LOOP.run_in_executor(None, cls._dump)

    # ### Interface ####
    @property
    def db(self) -> PostgreSQL:
        """ Get db config class instance """
        return Config.__DB_CONFIG

    @property
    def auth(self) -> Auth:
        """ Get auth config class instance """
        return Config.__AUTH_CONFIG

    @property
    def guilds(self) -> typing.Optional[typing.Dict[int, Guild]]:
        """ Get guilds config class instance """
        return Config.__GUILDS_CONFIG

    @property
    def bot_settings(self) -> typing.Optional[benedict]:
        """ Get bot settings """
        return Config.__BOT_SETTINGS or benedict(default_bot_settings,
                                                 keypath_separator=Config.__SEPARATOR)

    @property
    def owner_ids(self):
        """ Get owner ids of the bot if defined """
        return self.bot_settings.get_list("owner_ids")

    def get_api_key(self, api_name: str):
        """ Get api key by name """
        return Config.__API_CONFIG.get_str(api_name, None)

    @classmethod
    def get_guild_by_id(cls, guild_id: int) -> typing.Optional[Guild]:
        """ Get guild config class instance if exist else return None """
        return cls.__GUILDS_CONFIG.get(guild_id)

    @classmethod
    def get(cls, key: str, fallback: typing.Any) -> typing.Any:
        """
        Get any settings from raw config dict.
        Currently, because python benedict type is used under hook, you can
        use key-path as well to get an item.
        """
        assert cls.__RAW_CONFIG
        return cls.__RAW_CONFIG.get(key, fallback)

    @classmethod
    async def put(cls, key: str, value: typing.Any, guild_id: typing.Optional[int] = None):
        """
        Put any settings to raw config dict.
        Currently, because python benedict type is used under hook, you can
        use key-path as well to put the item.
        If guild id is given, the settings will change related to this guild.
        Else bot settings will change.

        Just give the setting name not full path like "min_days"
        """
        # cls.__RAW_CONFIG[key] = value
        # if guild_id is not None:
        #     cls.get_guild_by_id(guild_id).put(key, value)
        #     try:
        #         valid_kpath = f"guilds{cls.__SEPARATOR}{str(guild_id)}{cls.__SEPARATOR}{key}"
        #         cls.__RAW_CONFIG[] = value
        #     except KeyError:
        #         dicty[key] = value
        # else:
        cur_val = cls.__RAW_CONFIG.get(key)
        if cur_val is None or (cur_val and cur_val != value):
            cls.__RAW_CONFIG[key] = value
            await cls.save()
            cls.initialize_vars()

    @classmethod
    async def remove(cls, key: str, value):
        """
        Remove any settings to raw config dict.
        Currently, because python benedict type is used under hook, you can
        use key-path as well to put the item.
        """
        cls.__RAW_CONFIG.remove(key)
        await cls.save()
        cls.initialize_vars()


bot_config = Config(config_file_path=CONFIG_FILE_PATH, schema_file_path=SCHEMA_FILE_PATH)



# class Config:
#     @staticmethod
#     def set_conf(config_path: str):
#         config.read(config_path)
#
#     @staticmethod
#     def get_conf_key(section, key, fallback=None, value_type='str'):
#         value = fallback
#         if config.has_section(section):
#             if value_type == 'str':
#                 value = config.get(section, key, fallback=fallback)
#             elif value_type == 'bool':
#                 value = config.getboolean(section, key, fallback=fallback)
#             elif value_type == 'int':
#                 value = config.getint(section, key, fallback=fallback)
#             elif value_type == 'float':
#                 value = config.getfloat(section, key, fallback=fallback)
#             elif value_type == 'list':
#                 value = config.getlist(section, key, fallback=fallback)
#             else:
#                 raise TypeError(f'Given type: {value_type} is not defined.')
#
#         return value
#
#     @staticmethod
#     def set_conf_key(section, key, value):
#         if config.has_section(section):
#             config.set(section, key, value)
#
#
# class PostgreSQL:
#     PGHOST = get_env("PGHOST")
#     PGPORT = get_env("_PGPORT")
#     PGUSER = get_env("PGUSER")
#     PGDATABASE = get_env("PGDATABASE")
#     PGPASSWORD = get_env("PGPASSWORD")
#     DB_URL = get_env('DATABASE_URL')
#
#     @classmethod
#     def return_connection_str(cls):
#         if cls.DB_URL is not "":
#             return cls.DB_URL
#
#         return f"postgres://{cls.PGUSER}:{cls.PGPASSWORD}@{cls.PGHOST}:{cls.PGPORT}/{cls.PGDATABASE}"
#
#
# # read config file
# Config.set_conf(CONFIG_FILE)
#
# BOT_TOKEN = get_env("BOT_TOKEN")
# CLIENT_ID = get_env("CLIENT_ID")
# SENTRY_URL = get_env("SENTRY_URL")
#
# # ***** guild and channel settings *******
# GUILD_ID = int(environ.get("GUILD_ID", Config.get_conf_key('channels', "GUILD_ID", "648262260724203523")))
# LOGGING_CHANNEL_ID = int(
#     environ.get("LOGGING_CHANNEL_ID", Config.get_conf_key('channels', "LOGGING_CHANNEL_ID", "648867664026009621")))
# ANNOUNCEMENT_CHANNEL_ID = int(
#     environ.get("ANNOUNCEMENT_CHANNEL_ID", Config.get_conf_key('channels', "ANNOUNCEMENT_CHANNEL_ID", "653301549979795467")))
# CONFESSION_CHANNEL_ID = int(
#     environ.get("CONFESSION_CHANNEL_ID", Config.get_conf_key('channels', "CONFESSION_CHANNEL_ID", "750452002248458330")))
# RECEPTION_CHANNEL_ID = int(
#     environ.get("RECEPTION_CHANNEL_ID", Config.get_conf_key('channels', "RECEPTION_CHANNEL_ID", "648623592828960768")))
# ADMIN_CHANNEL_ID = int(
#     environ.get("ADMIN_CHANNEL_ID", Config.get_conf_key('channels', "ADMIN_CHANNEL_ID", "653695277605322761")))
# FEEDBACK_CHANNEL_ID = int(
#     environ.get("FEEDBACK_CHANNEL_ID", Config.get_conf_key('channels', "FEEDBACK_CHANNEL_ID", "653589800418410527")))
# # ****** people **********
# OWNER_ID = int(environ.get("OWNER_ID", Config.get_conf_key('members', "OWNER_ID", "647577161200566289")))
#
# # ##### admin cog constants #######
# # ***** roles ***********
# # role given for newcomers who not approved and waiting in a reception
# STRANGER_ROLE_NAME = 'Yabancılar'
# STRANGER_ROLE_ID = 648628529482825738
# # role given for members with top statistics
# LEADER_ROLE_NAME = 'Lider'
# # valid roles (higher is better)
# BOT_ROLE_ID = 651926730918854657
# # BOT_ROLE_NAME = 'Bot'
# # TIER1 = 'Çaylaklar'
# # TIER2 = 'Tecrübeliler'
# # TIER3 = 'Müdavimler'
# # TIER4 = 'Yönetim'
# # TIER5 = 'Sahip'
#
# TIER1 = 648264430089404437
# TIER2 = 653293626780024893
# TIER3 = 648262844089106453
# TIER4 = 648262492317024317
# TIER5 = 648262710990995467
# # role hierarchy
# ROLE_HIERARCHY = (TIER5, TIER4, TIER3, TIER2, TIER1)
# # role that activity rule will be determined
# ACTIVITY_ROLE_NAME = 'Aktif'
# ADMIN_ROLE_NAMES = (TIER5, TIER4)
# GENDER_ROLE_NAMES = ('Hanimefendi', 'Beyefendi', 'LGBT+')
# # roles that activity rule will effect
# ACTIVITY_INCLUDED_ROLES = (TIER2, TIER1)
# # roles use for getting stats
# STATS_ROLES = (TIER5, TIER4, TIER3, TIER2, TIER1, BOT_ROLE_ID, STRANGER_ROLE_ID)
# VALID_STATS_ROLES = (TIER5, TIER4, TIER3, TIER2, TIER1)
# # roles for using user command (getting number of days to upgrade next role)
# ROLE_UPGRADE_DAYS = {TIER1: (TIER2, 60), TIER2: (TIER3, 240)}
# # ***** constants ********
# # minimum number of needed days removing inactive members after last prune
# activity_schedule_gap = '5d'
# # minimum number of days passed since a member joined to be effected by activity removal rule
# activity_min_day = 7
# # text template for activity announcement
# activity_template = '{} tarihine kadar aktiflik sartini saglamaz veya yonetime mazeret ' \
#                     'bildirmez ise cikartilacak uye listesi'
# # text template for activity announcement in pm channel
# activity_pm_template = 'Bu mesajı sana {} dan gönderiyorum.' \
#                        'Artık seni aramızda sık sık göremiyoruz ve bu bizi çok üzüyor 😔 . ' \
#                        'Aktiflik rolüne sahip olmadığın için seni atılacak üye listesine ekledik. ' \
#                        'Eğer {} tarihine kadar aktif rolünü kazanmazsan veya yönetime eksikliğinin ' \
#                        'mazeretini bildirmez isen maalesef seni yukarıdaki tarihte kanaldan atmak zorunda kalacağım 😢 .'
# # text template to send removed members to rejoin if they would like to
# removed_member_pm_template = 'Tekrar merhaba! Aktiflik rolünü daha önce belirtilen tarihe kadar ' \
#                              'kazanamadığın için {} sunucusundan çıkartıldın. Ama bu herşeyin sonu demek değil. ' \
#                              'Senin için yeni bir davet oluşturdum, işte burda: {} \n Bu davet linki ile istersen ' \
#                              'bize tekrar katılabilirsin, unutma bu davet sadece {} gün geçerli olacak. ' \
#                              'Davete tıklayıp yeniden kanala katıldığında bu sefer aktif olacağına ' \
#                              'dair bana söz vermiş olacaksın, unutma!!!'
#
# # role upgrade template
# role_upgrade_template = 'Tebrikler {}! {} rolunden {} rolune yukseldin!'
# # number of days for checking role upgrade
# role_upgrade_gap = '1d'
# # minimum number of days for role transitions
# TIER1toTIER2 = 60
# TIER2toTIER3 = 240
# # directory for json permission templates
# base_json_dir = 'json_templates'
#
# # various delay value for operations such as message deletion
# short_delay = Config.get_conf_key('main', "short_delay", 60, value_type='int')
# mid_delay = Config.get_conf_key('main', "mid_delay", 120, value_type='int')
# long_delay = Config.get_conf_key('main', "long_delay", 300, value_type='int')
#
# # #### Confession cog #########
# message_timeout = Config.get_conf_key('confession', "message_timeout", 600, value_type='int')
# warn_limit = Config.get_conf_key('confession', "warn_limit", 3, value_type='int')
# command_cooldown = Config.get_conf_key('confession', "command_cooldown", 6000, value_type='int')
# valid_role_list = [TIER5, TIER4, TIER3, TIER2]
# valid_confession_roles = Config.get_conf_key('confession', "valid_confession_roles", valid_role_list, value_type='list')
# ##############################
#
# # #### Fun ####################
# TENOR_API_KEY = get_env("TENOR_API_KEY")
# # ############################
#
# # #### Cameradice #############
# max_lost_member = Config.get_conf_key('cameradice', "max_lost_member", 4, value_type='int')
# start_game_delay = Config.get_conf_key('cameradice', "start_game_delay", 10, value_type='int')
# ##############################
#
# # ### Truthdare  ##############
# # directory for json permission templates
# base_truthdare_dir = 'truthdare'
# ##############################
#
# # #### Automation cog #########
# # number of days the inactive members will be announced in announcement channel
# num_announce_days = Config.get_conf_key('announcement', "num_announce_days", 2, value_type='int')
# announcement_template = 'Maalesef aşağıda listelenen üyelerimiz kanalın aktiflik şartını sağlayamadıkları ' \
#                         'için **{}** rolüne sahip değiller. **{}** rolüne sahip olmayan bu üyeler olası bir aktif ' \
#                         'olmayan üyeleri çıkarma işleminde kanaldan **ATILACAKLARDIR!!!** Bu üyelerden ricamız ' \
#                         'lütfen en kısa sürede kanalda yeterince aktif olmaya başlamalarıdır.\n' \
#                         '** *Aşağıda mazeretlerini bildiren üyeler listelenmiştir, ' \
#                         'lütfen bu üyeler duyuruyu dikkate almasın. ' \
#                         'Bu üyeler haricinde eğer geçici bir mazeretiniz varsa lütfen yönetime bildirin.* ** \n' \
#                         '***Aktiflik şartı: https://sites.google.com/view/nightzone/ana-sayfa#h.p_6i1CL4wFpmQV***\n'
# ##############################
# # Emoji Alphabet
# EMOJI_LETTERS = [
#     "\U0001f1e6\U0001f170\U0001F359",  # A
#     "\U0001f1e7\U0001f171",  # B
#     "\U0001f1e8\u262a\u00A9",  # C
#     "\U0001f1e9\u21a9",  # D
#     "\U0001f1ea\U0001f4e7",  # E
#     "\U0001f1eb",  # F
#     "\U0001f1ec\u26fd",  # G
#     "\U0001f1ed\u2653",  # H
#     "\U0001f1ee\u2139",  # I
#     "\U0001f1ef\u2614",  # J
#     "\U0001f1f0",  # K
#     "\U0001f1f1\U0001f552\U0001F462",  # L
#     "\U0001f1f2\u24c2\u24c2\u264f\u264d\u303d",  # M
#     "\U0001f1f3\U0001f4c8\U0001F3B5",  # N
#     "\U0001f1f4\U0001f17e\u2b55",  # O
#     "\U0001f1f5\U0001f17f",  # P
#     "\U0001f1f6",  # Q
#     "\U0001f1f7",  # R
#     "\U0001f1f8\U0001f4b0\u26a1\U0001F4B2",  # S
#     "\U0001f1f9\u271d\U0001F334",  # T
#     "\U0001f1fa\u26ce",  # U
#     "\U0001f1fb\u2648",  # V
#     "\U0001f1fc\u3030",  # W
#     "\U0001f1fd\u274e\u274c\u2716",  # X
#     "\U0001f1fe\U0001f331\u270C",  # Y
#     "\U0001f1ff\U0001f4a4",  # Z
#     "\u26ab\U0001f535\U0001f534\u26aa",  # Whitespace alternatives
#     "\u2755\u2757\u2763",  # !
#     "\u2754\u2753",  # ?
#     "\U0001f4b2",  # $
#     "\U000021aa",  # (
#     "\U000021a9"  # )
# ]
