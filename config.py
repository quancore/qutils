import base64
from os import environ
from dotenv import load_dotenv

load_dotenv()

DEPLOY = bool(environ.get('DEPLOY'))


def get_env(name: str, fallback: str = "") -> str:
    """Return an (optionally base64-encoded) env var."""
    variable = environ.get(name)
    if DEPLOY and variable is not None:
        variable = base64.b64decode(variable).decode()
    return variable or fallback


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


BOT_TOKEN = get_env("BOT_TOKEN")
CLIENT_ID = get_env("CLIENT_ID")
SENTRY_URL = get_env("SENTRY_URL")

# guild and channel settings
GUILD_ID = int(environ.get("LOGGING_CHANNEL_ID", "648262260724203523"))
LOGGING_CHANNEL_ID = int(environ.get("LOGGING_CHANNEL_ID", "648867664026009621"))
ANNOUNCEMENT_CHANNEL_ID = int(environ.get("ANNOUNCEMENT_CHANNEL_ID", "653301549979795467"))


# ##### admin cog constants #######
# ****** people **********
OWNER_ID = '647577161200566289'

# ***** roles ***********
# role given for newcomers who not approved and waiting in a reception
STRANGER_ROLE_NAME = 'Yabancılar'
# valid roles (higher is better)
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

# ***** constants ********
# minimum number of needed days removing inactive members after last prune
activity_schedule_gap = '5min'
# minimum number of days passed since a member joined to be effected by activity rule
activity_min_day = 7
# text template for activity announcement
activity_template = '{} tarihine kadar aktiflik sartini saglamaz veya yonetime mazeret ' \
                    'bildirmez ise cikartilacak uye listesi'
# role upgrade template
role_upgrade_template = 'Tebrikler {}! {} rolunden {} rolune yukseldin!'
# number of days for checking role upgrade
role_upgrade_gap = '1d'
# minimum number of days for role transitions
TIER1toTIER2 = 60
TIER2toTIER3 = 240

# Fun constants
# QUOTES_CHANNEL_ID = int(environ.get("QUOTES_CHANNEL_ID", "463657120441696256"))
# QUOTES_BOT_ID = 292953664492929025
# WELCOME_BOT_ID = 155149108183695360

# Misc roles
# HUNDRED_PERCENT_ROLE_ID = 640481360766697482
# TRUE_HUNDRED_PERCENT_ROLE_ID = 640481628292120576

# # Lists for administration
# STAFF_ROLE_ID = 450063890362138624
# FAKE_ROLE_ID = 533826912712130580
# STATIC_NICKNAME_ROLE_ID = 567259415393075210
# CD_BOT_ROLE_ID = 543768819844251658
# ADMIN_MENTOR_ROLE_ID = 502238208747110411
# ROOT_ROLE_ID = int(environ.get("ROOT_MEMBERS_ID", "450113490590629888"))
# SUDO_ROLE_ID = int(environ.get("SUDO_MEMBERS_ID", "450113682542952451"))
# ADMIN_ROLES = ("Root", "Sudo")
# BANNED_DOMAINS = ["discord.gg"]


# class Roles:
#
#     class Elite:
#         MAIN = int(environ.get("ELITE_MEMBERS_ID", "580387468336037888"))
#
#         class London:
#             YOUNGER = int(environ.get("LDN_Y_MEMBERS_ID", "580387877385404428"))
#             OLDER = int(environ.get("LDN_O_MEMBERS_ID", "580387897644023811"))
#
#         class Birmingham:
#             YOUNGER = int(environ.get("BRM_Y_MEMBERS_ID", "580387895299276830"))
#             OLDER = int(environ.get("BRM_O_MEMBERS_ID", "580387899833581572"))
#
#         class Lancaster:
#             YOUNGER = int(environ.get("LAN_Y_MEMBERS_ID", "580387892853997578"))
#             OLDER = int(environ.get("LAN_O_MEMBERS_ID", "580387898973618176"))
#
#     class Exchange:
#         SHORTLIST = int(environ.get("EXCH_S_MEMBERS_ID", "582894164597932034"))
#         CONFIRMED = int(environ.get("EXCH_C_MEMBERS_ID", "585150522336608256"))
#
#
# # Cyber Constants
# HINTS_LIMIT = 8
# CYBERDISC_ICON_URL = "https://pbs.twimg.com/profile_images/921313066515615745/fLEl2Gfa_400x400.jpg"
# ELITECOUNT_ENABLED = False
#
# # Readme command constants
# README_SEND_ALIASES = ["create", "push", "generate", "send", "make", "build", "upload"]
# README_RECV_ALIASES = ["fetch", "get", "pull", "download", "retrieve", "dm", "dl"]
#
# END_README_MESSAGE = (
#     "**Can't see any of the above?**\nIf you can't see any of the rich embeds above, try the"
#     " following: `Settings -> Text & Images -> Link Preview (Show website preview info from"
#     " links pasted into that chat)  -> ON`"
# )
#
# BASE_ALIASES = {
#     "Headquarters": ["headquarters", "main", "hq", "h"],
#     "Moonbase": ["moonbase", "python", "moon", "m"],
#     "Forensics": ["forensics", "f"],
#     "Volcano": ["volcano", "v", "volc"]
# }
#
# # Admin Constants
# PLACEHOLDER_NICKNAME = "Valued server member"
# NICKNAME_PATTERNS = [
#     r'(discord\.gg/)',  # invite links
#     r'(nigg|cunt|ligma|fag|nazi|hitler|\bpaki\b)',  # banned words
#     r'(http(s)?:\/\/.)?(www\.)?[-a-zA-Z0-9@:%._\+~#=]{2,256}\.[a-z]{2,6}\b([-a-zA-Z0-9@:%_\+.~#?&//=]*)'  # hyperlinks
# ]

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