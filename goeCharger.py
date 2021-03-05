import requests
import json
import threading
import time
import math
import paho.mqtt.client as mqtt
import logging

from SMA_SunnyBoy import SMA_SunnyBoy
from TelegramBot import TelegramBot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# for testing purposes:
import random
def test_power():
    return random.uniform(4000, 8000)
###

class GOE_Charger:
    def __init__(self,address:str,name="",mqtt_topic="",mqtt_broker="",mqtt_port=1883,mqtt_transport=None,mqtt_path="/mqtt"):
        self.name = name
        self.address = address
        self.power_threshold = -1
        self.mqtt_enabled = False
        self.http_connection = None
        if mqtt_topic and mqtt_broker and mqtt_port:
            self.mqtt_topic = mqtt_topic
            self.mqtt_broker = mqtt_broker
            self.mqtt_port = mqtt_port
            self.mqtt_transport = mqtt_transport
            self.mqtt_path = mqtt_path
            if self.mqtt_transport:
                self.mqtt_client = mqtt.Client(self.mqtt_transport)
                self.mqtt_client.ws_set_options(path=self.mqtt_path, headers=None)
            else:
                self.mqtt_client = mqtt.Client()
            self.mqtt_client.on_connect = self.mqtt_on_connect
            self.mqtt_client.on_message = self.mqtt_on_message
            self.mqtt_client.connect_async(self.mqtt_broker,self.mqtt_port,60)
            self.mqtt_client.loop_start()
            timeout = 0
            while not self.mqtt_connected and timeout < 5:
                logger.info("Trying to connect to mqtt broker")
                timeout += 1
                time.sleep(5)
            self.mqtt_loop_run = None
            self.mqtt_loop_running = None


    def start_loop(self):
        self.mqtt_loop_run = True
        self.update_loop()

    def stop_loop(self):
        self.mqtt_client.loop_stop()
        self.mqtt_loop_run = False

    def update_loop(self):
        while self.mqtt_loop_run:
            self.mqtt_loop_running = True
            if self.mqtt_connected:
                topic = self.mqtt_topic+"/status"

                self.mqtt_publish(topic+"/httpc",self.http_connection,retain=True)

                self.mqtt_publish(topic+"/car",self.car,retain=True)
                if not self.http_connection:
                    continue

                self.mqtt_publish(topic+"/amp",self.amp,retain=True)

                self.mqtt_publish(topic+"/nrg",self.nrg,retain=True)

                self.mqtt_publish(topic+"/alw",self.alw,retain=True)

                self.mqtt_publish(topic+"/min-amp",self.power_threshold,retain=True)

            time.sleep(5)
        self.mqtt_loop_running = False

    @property
    def mqtt_connected(self):
        try:
            return self.mqtt_client.is_connected()
        except:
            return False

    # The callback for when the client receives a CONNACK response from the server.
    def mqtt_on_connect(self, client, userdata, flags, rc):
        logger.info("Connected with result code "+str(rc))

        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        self.mqtt_client.subscribe(self.mqtt_topic+"/command/#")

    # The callback for when a PUBLISH message is received from the server.
    def mqtt_on_message(self, client, userdata, msg):
        logger.info(msg.topic+" "+str(msg.payload))
        data = msg.payload.decode("utf-8")
        topic = msg.topic
        topics = topic.split("/")
        if data:
            if "command" in topics[-2]:
                if "alw" == topics[-1]:
                    data = True if data == "True" else False
                    self.alw = bool(data)
                    pass

                if "amp" == topics[-1]:
                    amp_setting = int(data)
                    if amp_setting <= 16 and amp_setting >=6:
                        self.amp = amp_setting

                if "min-amp" == topics[-1]:
                    min_amp_setting = int(data)
                    if min_amp_setting <= 16 and min_amp_setting >=6:
                        self.power_threshold = min_amp_setting

    def mqtt_publish(self, topic=None, payload=None, qos=0, retain=False):
        if topic is None:
            topic = self.mqtt_topic
        logger.info("Publishing: %s %s %s %s", topic, payload, qos, retain)
        return self.mqtt_client.publish(topic, payload, qos, retain)

    @property
    def data(self):
        r = None
        try:
            r = requests.get(self.address+"/status")
            self.http_connection = True
        except requests.exceptions.ConnectionError as e:
            logger.error("Connection error: %s", e)
            self.http_connection = False
        if r:
            return json.loads(r.text)
        else:
            return None

    @property
    def amp(self):
        data = self.data
        if data:
            return data.get("amp")
        else:
            return None

    @property
    def car(self):
        data = self.data
        if data:
            return data.get("car")
        else:
            return None

    @property
    def alw(self):
        data = self.data
        if data:
            return True if data.get("alw") == "1" else False
        else:
            return None

    @property
    def nrg(self):
        data = self.data
        if data:
            return data.get("nrg")[11]*10 # Watts
        else:
            return None

    @alw.setter
    def alw(self, value:bool):
        self._set("alw",int(value))

    @amp.setter
    def amp(self, value:int):
        self._set("amp",int(value))

    def _set(self,key:str,value):
        address = self.address +"/mqtt?payload="+key+"="+str(value)
        try:
            r = requests.get(address)
            self.http_connection = True
        except requests.exceptions.ConnectionError as e:
            logger.error("Connection error: %s", e)
            self.http_connection = False
        pass

    def power_to_amp(self,power:float):
        """Calculate amps from power for 3 phase ac.

        Args:
            power (float): power in watts

        Returns:
            float: amps in ampere
        """
        u_eff = 3*230
        i = power/u_eff
        return i

    def init_amp_from_power(self,get_power):
        self.get_power = get_power
        self.get_power = self._random

    # for testing purposes
    def _random(self, args):
        return random.uniform(4000/2.8, 8000/2.8)

    def loop(self,update_period):
        control_active = True
        state = "auto"
        state_old = state
        charging = False
        while True:
            power = self.get_power("power")
            if power < 0.0:
                power = 0.0
            power = power * 2.8
            amps = int(self.power_to_amp(power))

            if self.data.get("uby") != "0":
                state = "override"
            else:
                state = "auto"

            if not control_active and self.alw:
                state = "override"
            else:
                state = "auto"

            if state == "auto":
                if amps >= self.power_threshold and self.power_threshold >= 0:
                    control_active = True
                    # self.set_alw(True)
                    self.set_amp(amps)
                    if not charging:
                        self.telegramBot.sendMessage(self.telegramBot.chat_id,"Charging with "+str(int(power))+" W")
                        charging = True
                else:
                    control_active = False
                    self.set_alw(False)
                    self.set_amp(6)
                    if charging:
                        self.telegramBot.sendMessage(self.telegramBot.chat_id,"Stopped charging")
                        charging = False

            if state != state_old:
                self.telegramBot.sendMessage(self.telegramBot.chat_id,"State changed to " + state)

            state_old = state
            time.sleep(update_period)

    def start_controller(self, update_period=120):
        thread = threading.Thread(target=self.loop, args=(update_period,))
        thread.start()

class Inverter(SMA_SunnyBoy):
    def __init__(self, ipAddress:str):
        self.ipAddress = ipAddress
        super(Inverter, self).__init__(ipAddress)

class Goe_TelegramBot(TelegramBot):

    def change_power_threshhold(self, power_threshold):
        self.goe_charger.power_threshold = self.goe_charger.power_to_amp(float(power_threshold))

    def loop(self,update_period):
        self.chat_id = "419394316"
        while True:
            getMe = self.getMe()
            getChat= self.getChat(self.chat_id)
            new_messages = self.get_new_messages()
            if new_messages:
                for message in new_messages:
                    self.sendMessage(self.chat_id,"got message: \""+message["message"]["text"]+"\"")
                    if message["commands"]:
                        commands = message["commands"]
                        for command in commands:
                            if command == "power":
                                self.change_power_threshhold(commands[command])
                        pass
            time.sleep(update_period)

def main():
    sunny_inverter = Inverter("192.168.178.128")
    goe_charger = GOE_Charger('http://192.168.178.106')
    goe_charger.init_amp_from_power(sunny_inverter.read_value)

    # .gitignore
    telegramBot = Goe_TelegramBot('1628918536:AAHgSqaz71agbfvP9159vA5DCdKgB7lg8GE') # schwanzuslongus_bot
    telegramBot.goe_charger = goe_charger
    goe_charger.telegramBot = telegramBot
    r = telegramBot.setMyCommands([{"command":"hello", "description":"Say hello"},{"command":"test", "description":"Say test"}])
    commands = telegramBot.getMyCommands()

    goe_charger.start_controller(update_period=20)
    telegramBot.start(update_period=5)

if __name__ == '__main__':
    main()
