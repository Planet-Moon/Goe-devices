from goeCharger import GOE_Charger as GoeCharger
import time

ipAddress = "http://192.168.178.106"
mqtt_topic = "/home_test_server/goe_charger/GoeCharger1"
# mqtt_broker = "broker.hivemq.com"
mqtt_broker = "192.168.178.107"
mqtt_port = 1883 # TCP
mqtt_transport=None
mqtt_path="/mqtt"

websocket = False # websockets not working properly!?
if websocket:
    mqtt_port = 9002 # Websocket
    mqtt_transport = "websockets"
    mqtt_path = ""

goe_charger = GoeCharger(
    ipAddress,
    mqtt_topic,
    mqtt_broker,
    mqtt_port,
    mqtt_transport,
    mqtt_path,
    )

for i in range(5):
    print(goe_charger.mqtt_publish("hello world"))
    time.sleep(1)

while True:
    time.sleep(10)
pass
