from goeCharger import GOE_Charger as GoeCharger
import time

goe_charger = GoeCharger("http://192.168.178.106","/home_test_server/goe_charger/GoeCharger1","broker.hivemq.com",1883)

for i in range(5):
    print(goe_charger.mqtt_publish("hello world"))
    time.sleep(1)

while True:
    time.sleep(10)
pass
