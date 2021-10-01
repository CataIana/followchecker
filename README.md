This is something I made in a few hours from the pieces of another bot that I have yet to publish. Allows you to recieve notifications for follows to subscribed channels, and if authorized, block said users. 

Notes: Due to the nature of follow bots unfollowing shortly after following, the script waits 10 seconds and checks if they are still following.

I barely checked this before publishing it, there might be problems

Quick setup

* Fill in `exampleauth.json` and rename it to `auth.json`
* Install the requirements using the provided requirements.txt file `sudo pip3 install --upgrade -r requirements.txt`
* Be sure to add a redirect URI to the twitch application. Example: https://example.com/authorize. Make sure to include the /authorize
* Run the bot with `python3 main.py`