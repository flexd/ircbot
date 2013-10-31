# twisted imports
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol, defer
from twisted.python import log

# system imports
import time
import sys

from redis import Redis
redis = Redis()


class RateLimit(object):
    expiration_window = 10

    def __init__(self, key_prefix, limit, per):
        self.reset = (int(time.time()) // per) * per + per
        self.key = key_prefix + str(self.reset)
        self.limit = limit
        self.per = per
        p = redis.pipeline()
        p.incr(self.key)
        p.expireat(self.key, self.reset + self.expiration_window)
        self.current = min(p.execute()[0], limit)

    remaining = property(lambda x: x.limit - x.current)
    over_limit = property(lambda x: x.current >= x.limit)


class MessageLogger:
    """
    An independent logger class (because separation of application
    and protocol logic is a good thing).
    """
    def __init__(self, file):
        self.file = file

    def log(self, message):
        """Write a message to the file."""
        timestamp = time.strftime("[%H:%M:%S]", time.localtime(time.time()))
        self.file.write('%s %s\n' % (timestamp, message))
        self.file.flush()

    def close(self):
        self.file.close()


class LogBot(irc.IRCClient):
    """A logging IRC bot."""

    nickname = "belt"

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        self.logger = MessageLogger(open(self.factory.filename, "a"))
        self.logger.log("[connected at %s]" %
                        time.asctime(time.localtime(time.time())))

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        self.logger.log("[disconnected at %s]" %
                        time.asctime(time.localtime(time.time())))
        self.logger.close()

    # callbacks for events
    def signedOn(self):
        """Called when bot has succesfully signed on to server."""
        self.join(self.factory.channel)

    def userJoined(self, user, channel):
        print user.split("!", 1)

    def kickedFrom(self, channel, kicker, message):
        self.join(channel)

    def joined(self, channel):
        """This will get called when the bot joins the channel."""
        self.logger.log("[I have joined %s]" % channel)

    def privmsg(self, user, channel, msg):
        """This will get called when the bot receives a message."""
        user, host = user.split('!', 1)
        print host
        self.logger.log("<%s> %s" % (user, msg))

        # Check to see if they're sending me a private message
        if channel == self.nickname and host == "~flexd@dev.flexd.net":
            #  Just to keep with "standards", if command == "stuff".
            command = msg
            if (len(msg.split(" ")) > 1):
                command, args = msg.split(" ")
                if command:
                    if (command == "op"):
                        self.mode(self.factory.channel, True, 'o', user=args)
                        self.msg(user, "Yes sir!")
                    elif (command == "deop"):
                        self.mode(self.factory.channel, False, 'o', user=args)
                        self.msg(user, "Yes sir!")
                    elif (command == "voice"):
                        self.mode(self.factory.channel, True, 'v', user=args)
                        self.msg(user, "Yes sir!")
                    elif (command == "devoice"):
                        self.mode(self.factory.channel, False, 'v', user=args)
                        self.msg(user, "Yes sir!")
            else: # No arguments
                if (command == "opme"):
                    self.mode(self.factory.channel, True, 'o', user=user)
                    self.msg(user, "Yes sir!")
                elif (command == "deopme"):
                    self.mode(self.factory.channel, False, 'o', user=user)
                    self.msg(user, "Yes sir!")
                elif (command == "rate-limit"):
                    rate = redis.get("rate-limit-rate")
                    timewindow = redis.get("rate-limit-window")
                    self.msg(user, "Rate-limit is: %s messages per %s seconds" % (rate, timewindow))
        else: # channel message
            key = 'rate-limit/%s/%s/' % (channel, host)
            rlimit = RateLimit(key, int(redis.get("rate-limit-rate")), int(redis.get("rate-limit-window"))) # 5 messages per 2 seconds
            if rlimit.over_limit:
                self.kick(channel, user, "Stop flooding")
            # Otherwise check to see if it is a message directed at me
            if msg.startswith(self.nickname + ":"):
                msg = "%s: I am a bot" % user
                self.msg(channel, msg)
                self.logger.log("<%s> %s" % (self.nickname, msg))

    def action(self, user, channel, msg):
        """This will get called when the bot sees someone do an action."""
        user = user.split('!', 1)[0]
        self.logger.log("* %s %s" % (user, msg))

    # irc callbacks

    def irc_NICK(self, prefix, params):
        """Called when an IRC user changes their nickname."""
        old_nick = prefix.split('!')[0]
        new_nick = params[0]
        self.logger.log("%s is now known as %s" % (old_nick, new_nick))

    # For fun, override the method that determines how a nickname is changed on
    # collisions. The default method appends an underscore.
    def alterCollidedNick(self, nickname):
        """
        Generate an altered version of a nickname that caused a collision in an
        effort to create an unused related name for subsequent registration.
        """
        return nickname + '^'


class BotFactory(protocol.ClientFactory):
    """A factory for LogBots.

    A new protocol instance will be created each time we connect to the server.
    """

    def __init__(self, channel, filename):
        self.channel = channel
        self.filename = filename

    def buildProtocol(self, addr):
        p = LogBot()
        p.factory = self
        return p

    def clientConnectionLost(self, connector, reason):
        """If we get disconnected, reconnect to server."""
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print "connection failed:", reason
        reactor.stop()


if __name__ == '__main__':
    # initialize logging
    log.startLogging(sys.stdout)

    # create factory protocol and application
    f = BotFactory("#nff.spill", "out.log")

    # connect factory to this host and port
    reactor.connectTCP("irc.efnet.org", 6667, f)

    # run bot
    reactor.run()
