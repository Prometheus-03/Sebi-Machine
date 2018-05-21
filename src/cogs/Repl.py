import discord
from discord.ext import commands
import asyncio

import traceback
import inspect
import textwrap
from contextlib import redirect_stdout
import io
import aiohttp
import os
import time

class REPL:
    def __init__(self, bot):
        self.bot = bot
        self._last_result = None
        self.sessions = set()
        
    async def haste(self, content):
        async with self.bot.csess.post('https://hastebin.com/documents', data=content.encode('utf-8')) as r:
            a = await r.json()
            return f'https://hastebin.com/{a["key"]}.py'
            
    def cleanup_code(self, content):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith('```') and content.endswith('```'):
            return '\n'.join(content.split('\n')[1:-1])
        return content.strip('` \n')

    def get_syntax_error(self, e):
        if e.text is None:
            return '```py\n{0.__class__.__name__}: {0}\n```'.format(e)
        return '```py\n{0.text}{1:>{0.offset}}\n{2}: {0}```'.format(e, '^', type(e).__name__)
        
    @commands.command(pass_context=True, hidden=True, name='eval', aliases=['exec'])
    @commands.is_owner()
    async def _eval(self, ctx, *, body: str):
        env = {
            'bot': self.bot,
            'ctx': ctx,
            'channel': ctx.message.channel,
            'author': ctx.message.author,
            'guild': ctx.message.guild,
            'message': ctx.message,
            'aiohttp' : aiohttp,
            'inspect' : inspect,
            'discord' : discord,
            'commands' : commands,
            'os' : os,
            '_': self._last_result
        }

        env.update(globals())

        body = self.cleanup_code(body)

        try:
            compile(body, '<eval>', 'eval')
            return await ctx.invoke(self.bot.get_command('debug'), code=body)
        except:
            pass

        stdout = io.StringIO()

        to_compile = 'async def func():\n%s' % textwrap.indent(body, '  ')

        before = time.monotonic()

        try:
            exec(to_compile, env)
        except SyntaxError as e:
            return await ctx.send(self.get_syntax_error(e))

        func = env['func']

        try:
            with redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            value = stdout.getvalue()
            await ctx.send('```py\n{}{}\n```'.format(value, traceback.format_exc()))
        else:
            after = time.monotonic()
            total = (after-before)*1000
            value = stdout.getvalue()
            try:
                await ctx.message.add_reaction('\u2705')
            except:
                pass

            if len(value) > 2000:
                value = await self.haste(value)
            if ret is not None:
                if len(str(ret)) > 2000:
                    ret = await self.haste(str(ret))

            if ret is None:
                if value:
                    await ctx.send(f'\u23f0 Execution time: **{total:.3f}ms**\n```py\n{value}```')
            else:
                await ctx.send(f'\u23f0 Execution time: **{total:.3f}ms**\n```py\n{value}{ret}\n```')

    @commands.command(hidden=True)
    @commands.is_owner()
    async def repl(self, ctx):
        msg = ctx.message
        variables = {
            'bot': self.bot,
            'ctx': ctx,
            'channel': msg.channel,
            'author': msg.author,
            'guild': msg.guild,
            'message': msg,
            'aiohttp' : aiohttp,
            'inspect' : inspect,
            'discord' : discord,
            'commands' : commands,
            'os' : os,
            '_': None
        }

        if msg.channel.id in self.sessions:
            return await ctx.send('Already running a REPL session in this channel. Exit it with `quit`.')

        self.sessions.add(msg.channel.id)
        await ctx.send('Enter code to execute or evaluate. `exit()` or `quit` to exit.')

        while True:
            response = await self.bot.wait_for("message", check=lambda m: m.content.startswith('`') and m.channel == ctx.channel and m.author == msg.author)

            cleaned = self.cleanup_code(response.content)

            if cleaned in ('quit', 'exit', 'exit()'):
                await ctx.send('Exiting.')
                self.sessions.remove(msg.channel.id)
                return

            executor = exec
            if cleaned.count('\n') == 0:
                try:
                    code = compile(cleaned, '<repl session>', 'eval')
                except SyntaxError:
                    pass
                else:
                    executor = eval

            if executor is exec:
                try:
                    code = compile(cleaned, '<repl session>', 'exec')
                except SyntaxError as e:
                    await ctx.send(self.get_syntax_error(e))
                    continue

            variables['message'] = response

            fmt = None
            stdout = io.StringIO()

            try:
                with redirect_stdout(stdout):
                    result = executor(code, variables)
                    if inspect.isawaitable(result):
                        result = await result
            except Exception as e:
                value = stdout.getvalue()
                fmt = '```py\n{}{}\n```'.format(value, traceback.format_exc())
            else:
                value = stdout.getvalue()
                if result is not None:
                    fmt = '```py\n{}{}\n```'.format(value, result)
                    variables['_'] = result
                elif value:
                    fmt = '```py\n{}\n```'.format(value)

            try:
                if fmt is not None:
                    if len(fmt) > 2000:
                        h = await self.haste(fmt)
                        await msg.channel.send('Content too big to be printed. ' + h)
                    else:
                        await msg.channel.send(fmt)
            except discord.Forbidden:
                pass
            except discord.HTTPException as e:
                await msg.channel.send('Unexpected error: `{}`'.format(e))

    @commands.command(hidden=True)
    @commands.is_owner()
    async def debug(self, ctx, *, code : str):
        '''Evaluates code.'''
        code = code.strip('` ')
        result = None
        stdout = io.StringIO()
        env = {
            'bot': self.bot,
            'ctx': ctx,
            'message': ctx.message,
            'guild': ctx.message.guild,
            'channel': ctx.message.channel,
            'author': ctx.message.author,
            'aiohttp' : aiohttp,
            'discord' : discord,
            'inspect' : inspect
        }

        env.update(globals())

        try:
            with redirect_stdout(stdout):
                result = eval(code, env)
                if inspect.isawaitable(result):
                    result = await result
        except Exception as e:
            await ctx.send(f'```py\n{type(e).__name__} : {str(e)}```')
            return

        value = stdout.getvalue()

        if len(value) > 2000:
            value = await self.haste(value)
        if result is not None:
            if len(str(result)) > 2000:
                result = await self.haste(str(result))
        if result is None:
            if value:
                await ctx.send(f'```py\n{value}```')
        else:
            await ctx.send(f'```py\n{value}{result}\n```')

def setup(bot):
    bot.add_cog(REPL(bot))

