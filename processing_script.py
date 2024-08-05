from flask import Flask, request, jsonify
from pymongo import MongoClient
from threading import Thread, Lock
import time
import requests
import logging


# Set up logging
logging.basicConfig(level=logging.DEBUG)

# ESP32 endpoint URL (adjust this to your ESP32's IP address and endpoint)
ESP32_URL = 'http://192.168.1.8/update'

app = Flask(__name__)

# Global variable(s)
aqi = None
new_data = False

# MongoDB connection setup
client = MongoClient("mongodb+srv://isaac11:kanishk23@cluster0.bdljirk.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
db = client.sensor_data  # Database
action_collection = db.action  # Post data to this collection
sensorData_collection = db.readings # Receive data from collection
mode_collection = db.mode   # Receive data from collection

# Constants
valid_modes = ["AUTO", "TURBO", "SILENT", "SLEEP"]
AQI_MAX = 900
DUTY_CYCLE_MAX = 1900
DUTY_CYCLE_MIN_WORKING = 512
DUTY_CYCLE_MIN_IDLE = 412

# Shared variable(s)
# Declare  a global variable 'mode' with an initial value AUTO
mode = "AUTO"
mode_lock = Lock()

def map_value(value, in_min, in_max, out_min, out_max):
    # Scale input value from the input range to the output range       
    return (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min


# Responds to updation in PM2.5 levels
@app.route('/receiveAQI', methods=['POST'])
def notify_aqi():
    global aqi, new_data
    latest_sensor_document = request.json
    app.logger.debug("Received data: %s", latest_sensor_document)

    if not latest_sensor_document:
        app.logger.error("No data received")
        return jsonify({'error': 'No data received'}), 400

    if 'PM2.5' not in latest_sensor_document:
        app.logger.error("PM2.5 data missing")
        return jsonify({'error': 'PM2.5 data missing'}), 400

    aqi = latest_sensor_document['PM2.5']
    new_data = True
    return jsonify({'status': 'success'}), 200


def ledcolor(pm2_5):
    if(AQI_MAX > pm2_5 >= 150):
        red = int(255)
        green = int(0)
        blue = int(0)
    elif(150 > pm2_5 >= 100):
        red = int(255)
        green = int(255)
        blue = int(0)
    else:
        red = int(0)
        green = int(255)
        blue = int(0)
    return red, green, blue

# Update the collection 'readings'

def sendDatatoMongoDB(dutycycle,status,red,green,blue):
    document = {
        "DutyCycle" : dutycycle,
        "ISAAC_STATUS" : status,
        "RED" : red,
        "GREEN" : green,
        "BLUE" : blue
    }
    
    # Insert the document into the collection
    result = action_collection.insert_one(document)

    #Print the inserted document's ObjectID
    print(f"Data inserted successfully : {result.inserted_id}")


def mode_settings(function_mode):
    global aqi, new_data
    red,green,blue = ledcolor(aqi)

    if function_mode == "AUTO":
        dutycycle = map_value(aqi, 0,AQI_MAX, 0, DUTY_CYCLE_MAX)
        status = "Normal"
    elif function_mode == "TURBO":
        dutycycle = DUTY_CYCLE_MAX
        status = "Fast"
    elif function_mode == "SILENT":
        dutycycle == DUTY_CYCLE_MIN_WORKING
        status = "Slow"
    elif function_mode == "SLEEP":
        dutycycle == DUTY_CYCLE_MIN_IDLE
        status = "Stationary"
    else:
        return # Handle invalid mode gracefully
    if(new_data == True):
        sendDatatoMongoDB(dutycycle, status, red, green, blue)
        new_data = False

def monitor_mode():
    global mode
    while True:
        with mode_lock:
            current_mode = mode
            
        mode_settings(current_mode)
        time.sleep(60)


# Responds to the POST request  :   Receive the latest MODE
@app.route('/receiveMode', methods=['POST'])
def receive():
    global mode 
    if request.is_json:
        content = request.get_json()

        print("Received webhook payload: ")
        print(content)
        if(content.get('operationType') == 'insert'):
            received_mode = content.get('Mode')
            print(f'Received mode: {mode}')
        if received_mode in valid_modes:
            with mode_lock:
                mode = received_mode
                return jsonify({'message' : 'Valid mode received. Changing to {}'.format(received_mode) })
        else:
            return jsonify({'message' : 'Invalid mode received'})
            
    else:
        return jsonify({'message':'Invalid data format!'}), 400
    
''' Responds to the POST request  :   Receive the latest Action Parameters    :   Forward the parameters to ESP1 '''

@app.route('/notify_action', methods=['POST'])
def notify_action():
    data = request.json
    app.logger.debug("Received data: %s", data)
    
    if not data:
        app.logger.error("No data received")
        return jsonify({'error': 'No data received'}), 400
    
    # Send the data to the ESP32
    try:
        response = requests.post(ESP32_URL, json=data)
        app.logger.debug("Response from ESP32: %s", response.text)
        
        if response.status_code == 200:
            return jsonify({'status': 'success'}), 200
        else:
            app.logger.error("Failed to notify ESP32, status code: %s", response.status_code)
            return jsonify({'error': 'Failed to notify ESP32'}), 500
    except Exception as e:
        app.logger.exception("Exception occurred while notifying ESP32")
        return jsonify({'error': str(e)}), 500
    

if __name__ == "__main__":
    # Start the monitoring thread
    
    monitor_thread = Thread(target=monitor_mode)
    monitor_thread.daemon = True  # Allow the thread to exit when the main program exits
    monitor_thread.start()
    
    app.run(host = '0.0.0.0', port=5000,debug=True)
