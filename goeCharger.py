import requests
import json
import threading
import time
import math
import paho.mqtt.client as mqtt
import logging
import threading
from datetime import datetime

from SMA_SunnyBoy import SMA_SunnyBoy
from TelegramBot import TelegramBot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# for testing purposes:
import random
def test_power():
    return random.uniform(4000, 8000)
###

class Control_thread(threading.Thread):
    def __init__(self, goe_charger, solarInverter_ip, period_time=5, min_amp=-1):
        self.goe_charger = goe_charger
        self.solarInverter = SMA_SunnyBoy(solarInverter_ip)
        self.state = "Not started"
        self._run = True
        self.period_time = period_time
        threading.Thread.__init__(self, name=self.goe_charger.name+"_control_thread")

    def stop(self):
        self._run = False
        self.join()

    def run(self):
        control_active = True
        self.state = "auto"
        state_old = self.state
        charging = False
        while self._run:
            if self.goe_charger.control_mode == "solar":
                power = self.solarInverter.LeistungEinspeisung
                amp_setpoint = int(GOE_Charger.power_to_amp(power))

                try:
                    uby = self.goe_charger.data.get("uby")
                    alw = self.goe_charger.alw
                    min_amp = self.goe_charger.min_amp
                    amp = self.goe_charger.amp
                except:
                    time.sleep(self.period_time)
                    continue


                if uby != "0":
                    self.state = "override"
                else:
                    self.state = "auto"

                if not control_active and alw:
                    self.state = "override"
                else:
                    self.state = "auto"

                if self.state == "auto":
                    if amp_setpoint >= min_amp and min_amp >= 0:
                        control_active = True
                        # self.set_alw(True)
                        amp = amp_setpoint
                        if not charging:
                            logger.info("Charging with "+str(int(power))+" W")
                            charging = True
                    else:
                        control_active = False
                        alw = False
                        amp = min_amp
                        if charging:
                            logger.info("Stopped charging")
                            charging = False

                    try:
                        self.goe_charger.amp = amp
                        self.goe_charger.alw = alw
                    except:
                        pass

                if self.state != state_old:
                    logger.info("State changed to " + self.state)

            state_old = self.state
            time.sleep(self.period_time)

class GOE_Charger:
    def __init__(self,address:str,name="",mqtt_topic="",mqtt_broker="",mqtt_port=1883,mqtt_transport=None,mqtt_path="/mqtt"):
        self.name = name
        self.address = address
        self._data = {"last_read":datetime(2020,1,1)}
        self.control_mode = "on" if self.alw else "off"
        Control_thread(goe_charger=self,solarInverter_ip="192.168.178.128").start()
        self.get_error_counter = 0
        self.set_error_counter = 0
        self.min_amp = -1
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

                self.mqtt_publish(topic+"/min-amp",self.min_amp,retain=True)

                self.mqtt_publish(topic+"/control-mode",self.control_mode,retain=True)

                self.mqtt_publish(topic+"/update-time",datetime.now().isoformat(" ","seconds"),retain=True)

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
        try:
            data = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            return
        topic = msg.topic
        topics = topic.split("/")
        if data:
            if "command" in topics[-2]:
                if "alw" == topics[-1]:
                    data = True if data == "True" else False
                    self.alw = data
                    pass

                if "amp" == topics[-1]:
                    try:
                        amp_setting = int(data)
                    except ValueError:
                        return
                    if amp_setting <= 20 and amp_setting >=6:
                        self.amp = amp_setting

                if "min-amp" == topics[-1]:
                    try:
                        min_amp_setting = int(data)
                    except ValueError:
                        return
                    if min_amp_setting <= 20 and min_amp_setting >=6:
                        self.min_amp = min_amp_setting

                if "control-mode" == topics[-1]:
                    if data == "on":
                        self.control_mode = "on"
                        self.alw = True
                    if data == "off":
                        self.control_mode = "off"
                        self.alw = False
                    if data == "solar":
                        self.control_mode = "solar"


    def mqtt_publish(self, topic=None, payload=None, qos=0, retain=False):
        if topic is None:
            topic = self.mqtt_topic
        logger.info("Publishing: %s %s %s %s", topic, payload, qos, retain)
        return self.mqtt_client.publish(topic, payload, qos, retain)

    @property
    def data(self):
        time_now = datetime.now()
        time_passed = (time_now-self._data["last_read"]).seconds
        exceptions = []
        if time_passed >= 5:
            max_retries = 5
            retries = 0
            for retries in range(max_retries):
                try:
                    r = requests.get(self.address+"/status")
                    self.http_connection = True
                    result = json.loads(r.text)
                    result["last_read"] = datetime.now()
                    self._data = result
                    break
                except requests.exceptions.ConnectionError as e:
                    exceptions.append(e)
                    self.http_connection = False
                    self.get_error_counter += 1
                    logger.error("Errors encounterd: "+ self.get_error_counter)
                    logger.error("Retry: "+ retries)
                    time.sleep(2)
            for exception in exceptions:
                logger.error("Connection error: %s", exception)
        else:
            result = self._data
        return result

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
            self.set_error_counter += 1
        pass

    @staticmethod
    def power_to_amp(power:float):
        """Calculate amps from power for 3 phase ac.

        Args:
            power (float): power in watts

        Returns:
            float: amps in ampere
        """
        u_eff = 3*230 # Drehstrom
        i = power/u_eff
        return i

    # for testing purposes
    @staticmethod
    def _random():
        return random.uniform(4000/2.8, 8000/2.8)

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
    sunny_inverter = SMA_SunnyBoy("192.168.178.128")
    goe_charger = GOE_Charger('http://192.168.178.106')

    # .gitignore
    import _creds
    telegramBot = Goe_TelegramBot(_creds.telegramBot_Token)
    telegramBot.goe_charger = goe_charger
    goe_charger.telegramBot = telegramBot
    r = telegramBot.setMyCommands([{"command":"hello", "description":"Say hello"},{"command":"test", "description":"Say test"}])
    commands = telegramBot.getMyCommands()

    telegramBot.start(update_period=5)

if __name__ == '__main__':
    main()
