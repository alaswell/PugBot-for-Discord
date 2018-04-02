# PugBot for Discord

PugBot for discord is a bot for managing pickup games. This version has been updated and modified for use with [Fortress Forever](http://www.fortress-forever.com/) on steam.

## Installing

- Create a mongoDB to hold the last pickup and server + alias information. If you are unsure how to do this, a quick start tutorial can be found at the link provided below.
- Setup the mongoDB by running `python3 ./mongodb.py` on linux or `python mongodb.py` on windows
- Rename `config.py.example` to `config.py`
- Edit config.py to your liking
- Run the bot with `python3 ./pugbot.py` on linux or `python pugbot.py` on windows

## Requirements

- Python 3.5+
- [discord](https://github.com/Rapptz/discord.py)
- [pymongo](https://www.mongodb.com/blog/post/getting-started-with-python-and-mongodb)
- [python-valve](https://github.com/serverstf/python-valve)
- [requests](https://github.com/requests/requests)
