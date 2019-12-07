# PugBot for Discord

PugBot for discord is a bot for managing pickup games. This version has been updated and modified for use with [Fortress Forever](http://www.fortress-forever.com/) on steam.

## Installing

- I recommended that you run the bot on an aws EC2 or similar linux box 
  - Instructions for getting started can be found here https://aws.amazon.com/ec2/
- Once you have a linux box ready:
  - Create a mongoDB to hold the last pickup and server + alias information. If you are unsure how to do this, a quick start tutorial can be found at the link provided below.
  - Setup the mongoDB by running `python3 ./mongodb.py`
    - You will need to modify this file to match your game configuration
  - Rename `config.py.example` to `config.py`
    - Edit config.py to match your game configuration
  - Run the bot with the provided script `./runbot.sh`

## Requirements

- Python 3.5+
- [discord](https://github.com/Rapptz/discord.py)
- [pymongo](https://www.mongodb.com/blog/post/getting-started-with-python-and-mongodb)
- [python-valve](https://github.com/serverstf/python-valve)
- [requests](https://github.com/requests/requests)
