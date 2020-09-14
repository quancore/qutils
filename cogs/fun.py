from discord.ext import commands

import requests
# import pprint
from libneko import pag


class Fun(commands.Cog):
    base_tdk_url = "https://sozluk.gov.tr/gts"

    def __init__(self, bot):
        self.bot = bot

    # get a word meaning from Turkish Language Foundation
    @commands.command(name='tdk', help='Search a word meaning from TDK',
                     usage='phase \n For multiple words, use "...."')
    @commands.guild_only()
    async def tdk(self, ctx, phase: str):
        def get_str_from_list(list_of_dict, key, separator=', '):
            """ Get a key's value from given fetch_schedule of dicts as a separator concatenated """
            if list_of_dict is None:
                return ''

            return separator.join([_dict.get(key, '') for _dict in list_of_dict]).strip()

        phase = phase.replace('"', '')
        params = {'ara': phase}
        resp = requests.get(url=self.base_tdk_url, params=params)
        resp_struct = resp.json()
        is_error = isinstance(resp_struct, dict) and resp_struct.get('error', None) is not None

        if len(resp_struct) > 0 and not is_error:
            nav = pag.EmbedNavigatorFactory(max_lines=20)
            nav.add_line(f'__**{phase}** kelimesinin anlami__\n')
            meanings_dict = resp_struct[0]
            # pprint.pprint(meanings_dict)
            meanings = meanings_dict.get('anlamlarListe', [])
            other_language = meanings_dict.get('lisan', '')
            if other_language != '':
                nav.add_line(f'`{other_language}` \n')

            for index, meaning in enumerate(meanings):
                # pprint.pprint(meaning)
                # pprint.pprint('---------')
                examples = meaning.get('orneklerListe', [])
                properties = meaning.get('ozelliklerListe', [])
                example_str = ''
                properties_str = get_str_from_list(properties, 'tam_adi')
                for example in examples:
                    example_quota_str = f"{example.get('ornek', '')}"
                    example_writer_str = ''
                    example_writer = example.get('yazar', [])
                    if example_writer:
                        example_writer = example_writer[0]
                        example_writer_str = f"{example_writer.get('tam_adi', '')}"
                    if example_quota_str != '' and example_writer_str != '':
                        example_str += f'\n--> "{example_quota_str}" - **{example_writer_str}**'

                overall_str = f'**{index + 1}.** '
                if properties_str:
                    overall_str += f'`{properties_str}` '
                meaning_str = f"{meaning['anlam']}." if example_str == '' else f"{meaning['anlam']}:"
                overall_str += meaning_str
                if example_str:
                    overall_str += f'{example_str}'
                # overall_str += '```'
                nav.add_line(overall_str)
                # nav.add_line('**-----------------------------**')
                # pprint.pprint(meaning)

            nav.start(ctx=ctx)
        else:
            await ctx.send(f'We could not found a meaning for **{phase}**')


def setup(bot):
    bot.add_cog(Fun(bot))