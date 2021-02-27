import requests
import json
import threading
import time
import math

from SMA_SunnyBoy import SMA_SunnyBoy
from TelegramBot import TelegramBot

# for testing purposes:
import random
def test_power():
    return random.uniform(4000, 8000)
###

class GOE_Charger:
    def __init__(self,address:str):
        self.address = address
        self.power_threshold = -1

    @property
    def data(self):
        r = requests.get(self.address+"/status")
        return json.loads(r.text)

    @property
    def amp(self):
        return self.data.get("amp")

    @property
    def car(self):
        return self.data.get("car")

    @property
    def alw(self):
        return True if self.data.get("alw") == "1" else False

    def set_alw(self, value:bool):
        self._set("alw",int(value))

    def set_amp(self, value:int):
        self._set("amp",int(value))

    def _set(self,key:str,value):
        address = self.address +"/mqtt?payload="+key+"="+str(value)
        r = requests.get(address)
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
    goe_charger.init_amp_from_power(sunny_inverter.modbus.read_value)

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
