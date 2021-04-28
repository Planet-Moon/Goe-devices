import requests
import json
import threading
import time
import math
import paho.mqtt.client as mqtt
import logging
import threading
import copy
import math
from enum import IntEnum, unique
from datetime import datetime
import pytz
timezone = pytz.timezone("Europe/Berlin")

from SMA_SunnyBoy import SMA_SunnyBoy
from SMA_StorageBoy import SMA_StorageBoy
from piko_inverter import Piko_inverter
from TelegramBot import TelegramBot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# for testing purposes:
import random
def test_power():
    return random.uniform(4000, 8000)
###

class BatteryManager:

    @unique
    class State(IntEnum):
        STANDBY = 0,
        CHARGE = 1,
        DISCHARGE = 2

    def __init__(self,charge_power:int=3500,discharge_power:int=2000,limit_low:int=75,limit_high:int=85):
        self.state = self.State.STANDBY
        self.charge_power = charge_power
        self.discharge_power = discharge_power
        self.limit_low = limit_low
        self.limit_high = limit_high

    def _power_balance(self):
        if(self.state == self.State.CHARGE):
            return self.charge_power
        elif(self.state == self.State.DISCHARGE):
            return self.discharge_power
        elif(self.state == self.State.STANDBY):
            return 0
        else:
            raise ValueError("Unsupported state")

    def update(self,solar_power:float,battery_power:float,battery_charge:int,grid_power:float):
        if(grid_power > 0):
            self.state = self.State.DISCHARGE
        elif(battery_charge > 85):
            self.state = self.State.DISCHARGE
        elif(battery_charge < 75 and solar_power > 0):
            self.state = self.State.CHARGE

        return self.state, self._power_balance()

class Control_thread(threading.Thread):
    def __init__(self, goe_charger, solarInverter_ip, batteryInverter_ip, period_time=30):
        self.goe_charger = goe_charger
        self.solarInverter = SMA_SunnyBoy(solarInverter_ip)
        self.batteryInverter = SMA_StorageBoy(batteryInverter_ip)
        self.battery_state = -3500 if self.batteryInverter.AktuellerBatterieladezustand > 75 else 3500
        self.Piko_inverter = Piko_inverter()
        self.solar_power = lambda: self.solarInverter.power + self.Piko_inverter.power
        self.state = "Not started"
        self._run = True
        self.period_time = period_time
        threading.Thread.__init__(self, name=self.goe_charger.name+"_control_thread")

    def battery_power(self):
        lade_zustand = self.batteryInverter.AktuellerBatterieladezustand
        x = lade_zustand

        # self.battery_state = -3.666*lade_zustand**3 + \
        #     834.985*lade_zustand**2-63282.2178*lade_zustand + \
        #     1595971.8236

        if lade_zustand > 85:
            self.battery_state = -2000
        elif lade_zustand > 72 and lade_zustand < 78 and self.battery_state <= 0:
            self.battery_state = 0
        elif lade_zustand < 65:
            self.battery_state = 3500
        return self.battery_state

    def stop(self):
        self._run = False
        self.join()

    def run(self):

        class State:
            def __init__(self):
                self.control_state = "auto"
                self.control_active = False
                self.amp = 0

            @property
            def control_state(self):
                return self._control_state

            @control_state.setter
            def control_state(self,state):
                self._control_state = state

            def __eq__(self, other):
                if not isinstance(other, State):
                    # don't attempt to compare against unrelated types
                    return NotImplemented

                result = True
                if self.control_state != other.control_state:
                    result = False
                if self.control_active != other.control_active:
                    result = False
                if self.amp != other.amp:
                    result = False
                return result

        cs = State() # current state
        cs.amp = self.goe_charger.min_amp if self.goe_charger.min_amp >= 0 else 0
        ns = copy.copy(cs) # next state
        while not self.goe_charger.mqtt_connected:
            time.sleep(2)
        self.goe_charger.mqtt_publish(
            self.goe_charger.mqtt_topic+"/status"+"/control-status",
            cs.control_state,retain=True)

        while self._run:
            cs = copy.copy(ns)
            if self.goe_charger.control_mode == "solar":

                try:
                    # read values from goe_charger
                    uby = self.goe_charger.data.get("uby")
                    min_amp = self.goe_charger.min_amp
                    car = self.goe_charger.car
                    nrg = self.goe_charger.nrg # Watts
                except:
                    time.sleep(self.period_time)
                    continue

                solar_power = self.solar_power()
                battery_power = self.battery_power()
                power_delta = (solar_power - battery_power - self.solarInverter.LeistungBezug)/self.goe_charger.solar_ratio
                self.goe_charger.mqtt_publish(self.goe_charger.mqtt_topic+"/status/power-delta",payload=str(power_delta))
                if self.goe_charger.solar_ratio > 0:
                    amp_setpoint = math.floor(GOE_Charger.power_to_amp(power_delta))
                else:
                    amp_setpoint = min_amp

                power_setpoint = GOE_Charger.amp_to_power(amp_setpoint)
                self.goe_charger.mqtt_publish(self.goe_charger.mqtt_topic+"/status/power-setpoint",payload=str(power_setpoint))
                logger.debug("power_delta:" + str(power_delta))
                logger.debug("amp_setpoint:" + str(amp_setpoint))

                # Transition
                ns.control_state = "auto" # default value
                if uby != "0":
                    ns.control_state = "override"
                elif not cs.control_active and cs.control_active:
                    ns.control_state = "override"

                if cs.control_state == "auto":
                    if amp_setpoint >= min_amp and min_amp >= 0:
                        ns.control_active = True
                        ns.amp = amp_setpoint
                    else:
                        ns.control_active = False
                        ns.amp = min_amp
                if int(car) <= 1: # car not connected
                    ns.control_active = False

                # Output
                if ns != cs:
                    self.goe_charger.amp = ns.amp
                    self.goe_charger.alw = ns.control_active
                    logger.info("amp: "+str(ns.amp))
                    logger.info("control_active: "+str(ns.control_active))
                    if cs.control_state != ns.control_state:
                        logger.info("Control state changed to %s", ns.control_state)
                        if self.goe_charger.mqtt_connected:
                            topic = self.goe_charger.mqtt_topic+"/status"
                            self.goe_charger.mqtt_publish(topic+"/control-status",ns.control_state,retain=True)

                if ns.amp != cs.amp and cs.control_state == "auto":
                    logger.info("Charging with "+str(GOE_Charger.amp_to_power(ns.amp))+" W")

            time.sleep(self.period_time)

class GOE_Charger:
    def __init__(self,address:str,name="",mqtt_topic="",mqtt_broker="",mqtt_port=1883,mqtt_transport=None,mqtt_path="/mqtt"):
        self.name = name
        self.address = address
        self._data = {"last_read":timezone.localize(datetime(2020,1,1))}
        self.control_mode = "on" if self.alw else "off"
        self.get_error_counter = 0
        self.set_error_counter = 0
        self.min_amp = -1
        self.solar_ratio = 1.0 # range 0.0 - 1.0
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
                logger.warning("Trying to connect to mqtt broker")
                timeout += 1
                time.sleep(5)
            self.mqtt_loop_run = None
            self.mqtt_loop_running = None
        Control_thread(goe_charger=self,solarInverter_ip="192.168.178.128",batteryInverter_ip="192.168.178.113").start()


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

                self.mqtt_publish(topic+"/update-time",datetime.now(timezone).strftime("%Y-%m-%d %H:%M:%S"),retain=True)

                self.mqtt_publish(topic+"/solar-ratio",self.solar_ratio*100,retain=True) # MQTT sends percent

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

                if "solar-ratio" == topics[-1]:
                    self.solar_ratio = float(data)/100 # MQTT sends percent

    def mqtt_publish(self, topic=None, payload=None, qos=0, retain=False):
        if topic is None:
            topic = self.mqtt_topic
        logger.debug("Publishing: %s %s %s %s", topic, payload, qos, retain)
        return self.mqtt_client.publish(topic, payload, qos, retain)

    @property
    def data(self):
        time_now = datetime.now(timezone)
        time_passed = (time_now-self._data["last_read"]).seconds
        if time_passed >= 5:
            max_retries = 10
            retries = 0
            exceptions = []
            for retries in range(max_retries):
                try:
                    r = requests.get(self.address+"/status")
                    self.http_connection = True
                    json_string = r.text.replace(" ","")
                    if json_string[-1] == '}':
                        result = json.loads(json_string)
                    else:
                        raise requests.exceptions.ConnectionError
                    result["last_read"] = datetime.now(timezone)
                    self._data = result
                    break
                except requests.exceptions.ConnectionError as e:
                    exceptions.append(e)
                    self.http_connection = False
                    self.get_error_counter += 1
                    logger.error("Retry: {}".format(retries))
                    time.sleep(2)
            if exceptions:
                logger.error("Errors encounterd: {}".format(self.get_error_counter))
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

    @staticmethod
    def amp_to_power(amps:float):
        """Calculate power from amps for 3 phase ac.

        Args:
            amps (float): current in amps

        Returns:
            float: power in watt
        """

        u_eff = 3*230 # Drehstrom
        power = amps*u_eff
        return power

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
