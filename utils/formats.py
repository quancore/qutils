from io import StringIO, BytesIO
import csv
import random

from libneko import pag, Embed as libEmbed, unspecified_field, empty_field
from discord import Embed, Colour, utils

# These color constants are taken from discord.js library
colors = {
  'DEFAULT': 0x000000,
  'WHITE': 0xFFFFFF,
  'AQUA': 0x1ABC9C,
  'GREEN': 0x2ECC71,
  'BLUE': 0x3498DB,
  'PURPLE': 0x9B59B6,
  'LUMINOUS_VIVID_PINK': 0xE91E63,
  'GOLD': 0xF1C40F,
  'ORANGE': 0xE67E22,
  'RED': 0xE74C3C,
  'GREY': 0x95A5A6,
  'NAVY': 0x34495E,
  'DARK_AQUA': 0x11806A,
  'DARK_GREEN': 0x1F8B4C,
  'DARK_BLUE': 0x206694,
  'DARK_PURPLE': 0x71368A,
  'DARK_VIVID_PINK': 0xAD1457,
  'DARK_GOLD': 0xC27C0E,
  'DARK_ORANGE': 0xA84300,
  'DARK_RED': 0x992D22,
  'DARK_GREY': 0x979C9F,
  'DARKER_GREY': 0x7F8C8D,
  'LIGHT_GREY': 0xBCC0C0,
  'DARK_NAVY': 0x2C3E50,
  'BLURPLE': 0x7289DA,
  'GREYPLE': 0x99AAB5,
  'DARK_BUT_NOT_BLACK': 0x2C2F33,
  'NOT_QUITE_BLACK': 0x23272A
}


class Plural:
    def __init__(self, value):
        self.value = value

    def __format__(self, format_spec):
        v = self.value
        singular, sep, plural = format_spec.partition('|')
        plural = plural or f'{singular}s'
        if abs(v) != 1:
            return f'{v} {plural}'
        return f'{v} {singular}'


def human_join(seq, delim=', ', final='or'):
    size = len(seq)
    if size == 0:
        return ''

    if size == 1:
        return seq[0]

    if size == 2:
        return f'{seq[0]} {final} {seq[1]}'

    return delim.join(seq[:-1]) + f' {final} {seq[-1]}'


class TabularData:
    def __init__(self, line_break='\n'):
        self._widths = []
        self._columns = []
        self._table_rows = []
        self._csv_rows = []
        self._line_break = line_break

    def set_columns(self, columns):
        self._columns = columns
        self._widths = [len(c) + 2 for c in columns]

    def add_row(self, row, exception_index=None):
        # row element list_role for original and filtered table row
        valid_index = 0
        elements, table_elements = [], []
        for index, element in enumerate(row):
            element = str(element)
            elements.append(element)
            if exception_index and index not in exception_index:
                width = len(element) + 2
                if width > self._widths[valid_index]:
                    self._widths[valid_index] = width

                valid_index += 1

                table_elements.append(element)

        self._table_rows.append(table_elements)
        self._csv_rows.append(elements)

    def to_csv(self, column_list):
        in_memory_file = StringIO()
        csv_writer = csv.writer(in_memory_file)
        csv_writer.writerows([column_list, *self._csv_rows])
        in_memory_file.seek(0)

        return in_memory_file

    def set_col_width(self, col_name, width):
        try:
            col_index = self._columns.index(col_name)
        except ValueError:
            return
        else:
            self._widths[col_index] = width + 2

    def add_rows(self, rows, exception_index=None):
        for row in rows:
            self.add_row(row, exception_index)

    def get_entry(self, d, empty_char='\u2005'):
        elem = '|'.join(f'{e:{empty_char}^{self._widths[i]}}' for i, e in enumerate(d))
        return f'|{elem}|'

    def get_column_str(self, empty_char=' '):
        sep = '+'.join('-' * w for w in self._widths)
        sep = f'+{sep}+'
        col_str = self.get_entry(self._columns, empty_char)

        return self._line_break.join([sep, col_str, sep])

    def render(self, render_column=True, empty_char=' '):
        """Renders a table in rST format.

        Example:

        +-------+-----+
        | Name  | Age |
        +-------+-----+
        | Alice | 24  |
        |  Bob  | 19  |
        +-------+-----+
        """

        sep = '+'.join('-' * w for w in self._widths)
        sep = f'+{sep}+'

        to_draw = []
        col_str = ''
        if render_column:
            col_str = self.get_column_str()

        for row in self._table_rows:
            to_draw.append(self.get_entry(row, empty_char))

        to_draw.append(sep)
        return col_str + self._line_break.join(to_draw)


class CustomEmbed(libEmbed):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def to_dict(self) -> dict:
        result = super().to_dict()

        if hasattr(self, '_video'):
            result['video'] = self._video

        return result

    def to_embed(self):
        result = self.to_dict()
        return Embed.from_dict(result)

    @classmethod
    def from_dict(cls, data, is_thumbnail=True, author_name=None, avatar_url=None):
        """Converts a :class:`dict` to a :class:`Embed` provided it is in the
        format that Discord expects it to be in.

        You can find out about this format in the `official Discord documentation`__.

        .. _DiscordDocs: https://discordapp.com/developers/docs/resources/channel#embed-object

        __ DiscordDocs_

        Parameters
        -----------
        data: :class:`dict`
            The dictionary to convert into an embed.
        is_thumbnail: :class:`bool`
            Whether embed includes default thumbnail.
        author_name: :class:`str`
            The author name of a command if embed is a response a for the author.
        avatar_url: :class:`str`
            The avatar url of the bot.
        """
        # we are bypassing __init__ here since it doesn't apply here
        self = cls.__new__(cls)
        self.__init__()

        # fill in the basic fields

        self.title = data.get('title', unspecified_field)
        # self.type = data.get('type', unspecified_field)
        self.description = data.get('description', unspecified_field)
        self.url = data.get('url', unspecified_field)

        # try to fill in the more rich fields

        try:
            self.colour = Colour(value=data['color'])
        except KeyError:
            color_list = list(colors.values())
            self.colour = random.choice(color_list)

        try:
            self.timestamp = utils.parse_time(data['timestamp'])
        except KeyError:
            pass

        try:
            image = data['image']
        except KeyError:
            pass
        else:
            self.set_image(url=image.get('url', empty_field), proxy_url=image.get('proxy_url', empty_field))

        try:
            video = data['video']
        except KeyError:
            pass
        else:
            setattr(self, '_video', video)

        try:
            thumbnail = data['thumbnail']
        except KeyError:
            thumbnail = {}

            if avatar_url and is_thumbnail:
                thumbnail['url'] = str(avatar_url)
        finally:
            if 'url' in thumbnail or 'proxy_url' in thumbnail:
                self.set_thumbnail(url=thumbnail.get('url', empty_field), proxy_url=thumbnail.get('proxy_url', empty_field))

        try:
            author = data['author']
        except KeyError:
            pass
        else:
            self.set_author(name=author.get('name', unspecified_field), url=author.get('url', unspecified_field),
                            icon_url=author.get('icon_url', unspecified_field))

        footer = data.get('footer', {})
        text = footer.get('text', f'By {author_name}' if author_name else str(unspecified_field))
        icon_url = footer.get('icon_url', None)
        if icon_url is not None:
            self.set_footer(text=text, icon_url=icon_url)
        elif avatar_url is not None:
            self.set_footer(text=text, icon_url=str(avatar_url))
        else:
            self.set_footer(text=text)

        try:
            fields = data['fields']
        except KeyError:
            fields = []
        finally:
            for field in fields:
                name = field.get('name', None) or str(unspecified_field)
                value = field.get('value', None) or str(unspecified_field)
                self.add_field(name=name, value=value,
                               inline=field.get('inline', 'False'))

        return self


class EmbedGenerator(pag.AbstractEmbedGenerator):
    def __init__(self, format_dict=None, author_name=None, avatar_url=None):
        self.format_dict = format_dict
        self.author_name = author_name
        self.avatar_url = avatar_url

    @property
    def max_chars(self) -> int:
        return 2048

    @property
    def provides_numbering(self):
        return True

    def build_page(self, paginator: pag.Paginator, page: str, page_index: int) -> Embed:
        if self.format_dict:
            embed = CustomEmbed.from_dict(data=self.format_dict, author_name=self.author_name, avatar_url=self.avatar_url)

        else:
            embed = Embed()

        embed.description = page
        embed.set_footer(text=f"{embed.footer['text']} • p.{page_index + 1} of {len(paginator.pages)}",
                         icon_url=embed.footer['icon_url'])

        return embed


@pag.embed_generator(max_chars=2048)
def cooler_embed(paginator, page, page_index, context=None):
    return Embed.from_dict(context)
