# Ban Hammer Bot for use with Pickup-Bot-For-Discord
# Created by: Alex Laswell

import asyncio
import config
import discord
from discord import Game
from discord.ext.commands import Bot
import pymongo
import sys

# Configurable constants
adminChannelID = config.adminChannelID
adminRoleMention = config.adminRoleMention
bannedChannelID = config.bannedChannelID
cmdprefix = config.cmdprefix
dbtoken = config.dbtoken
discordServerID = config.discordServerID
playerRoleID = config.playerRoleID
timeoutRoleID = config.timeoutRoleID
token = config.banHammerToken

# Setup the required objects
Bot = Bot(command_prefix=cmdprefix)
client = discord.Client()
server = None
adminRole = None
accessRole = None
poolRole = None
timeoutRole = None

# create the MongoDB client and connect to the database
dbclient = pymongo.MongoClient(dbtoken)
database = dbclient.FortressForever

# Unban a user from the discord server
async def unban(userID):
    global adminChannelID, accessRole, bannedChannelID, database, dbclient, server, timeoutRole

    tries = 0
    while tries < 3:
        try:
            member = server.get_member(userID)
            # Search the mongoDB to make sure banned user is still banned
            query = database.banned.find({"userid": userID})
            try:
                query.next()
                # delete the ban from the MongoDB
                database.banned.delete_one({"userid": userID})

                # give user back access
                try:
                    await Bot.remove_roles(member, timeoutRole)
                    await asyncio.sleep(2)
                    await Bot.add_roles(member, accessRole)
                except Exception:
                    pass

                # notify the admins and banned users
                emb = discord.Embed(
                    description="The ban for user "
                    + member.mention
                    + " has been removed.\nThe time period has expired",
                    colour=0x00FF00,
                )
                emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
                await Bot.send_message(server.get_channel(bannedChannelID), embed=emb)
                await Bot.send_message(server.get_channel(adminChannelID), embed=emb)
                # notify the user
                emb = discord.Embed(
                    description="Your ban has been removed because the time period has expired.\nDo better this time",
                    colour=0x00FF00,
                )
                emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
                await Bot.send_message(member, embed=emb)
            except StopIteration:
                tries = 666
        except Exception:
            tries += 1
            pass  # ignore all errors and try again (3x total)
    dbclient.close()


# when ready the bot removes the ban from the mongoDB and gives the user access again
@Bot.event
async def on_ready():
    global adminRole, accessRole, playerRoleID, server, timeoutRole, timeoutRoleID
    await Bot.change_presence(game=Game(name="Unbanning " + sys.argv[1]))
    server = Bot.get_server(id=discordServerID)
    accessRole = discord.utils.get(server.roles, id=playerRoleID)
    timeoutRole = discord.utils.get(server.roles, id=timeoutRoleID)
    # unban the userID specified on the commandline
    await unban(sys.argv[1])
    sys.exit(0)


Bot.run(token)
