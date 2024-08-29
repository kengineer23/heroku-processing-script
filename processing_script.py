"""
@file app.py
@brief A Flask application for managing and monitoring air quality data and device modes.

This application receives air quality data, updates device modes, and communicates with an ESP32 device.
"""

from flask import Flask, request, jsonify,g
from pymongo import MongoClient 
from threading import Thread, Lock
import requests
import paho.mqtt.client as mqtt

device_id = ''

app = Flask(__name__)

# Global variable(s)
aqi = int()

# MongoDB connection setup
client = MongoClient("mongodb+srv://kanishk:kanishk23@isaactest.ldse4t5.mongodb.net/?retryWrites=true&w=majority&appName=IsaacTest")
db = client.isaac_v1  # Database
action_collection = db.action_params  # Post data to this collection
sensorData_collection = db.sensor_readings # Receive data from collection
mode_collection = db.isaac_modes # Receive data from collection
device_id_collection = client.device_id # Receive data from collection

# MQTT connection setup
mqtt_client = mqtt.Client()
mqtt_client.username_pw_set("wgreqkue", "Xfm3vi1pwbk_")

# Connect to the MQTT broker
mqtt_client.connect("driver.cloudmqtt.com", 18989, 60)
mqtt_client.loop_start()

# Constants
valid_modes = ["0", "1", "2", "3"]      # [AUTO, TURBO, SILENT, SLEEP]
AQI_MAX = 900
DUTY_CYCLE_MAX = 1900
DUTY_CYCLE_MIN_WORKING = 512
DUTY_CYCLE_MIN_IDLE = 412
THRESHOLD_HIGH = 150
THRESHOLD_MEDIUM = 100

# Shared variable(s)
# Declare a global variable 'mode' with an initial value 0
mode = "0"
mode_lock = Lock()


@app.route('/receiveDeviceID', methods=['POST'])
def receiveID():
    global device_id
    # Check if the request is JSON
    if not request.is_json:
        app.logger.error("Invalid JSON received")
        return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400
    
    app.logger.info("Received data")

    # Parse JSON data
    try:
        received_data = request.get_json()
        app.logger.debug(f"Received JSON data: {received_data}")
    except Exception as e:
        app.logger.error(f"Error parsing JSON: {e}")
        return jsonify({'status': 'error', 'message': 'Invalid JSON format'}), 400

    # Validate required fields
    if 'fullDocument' not in received_data:
        app.logger.error("Missing 'fullDocument' in received data")
        return jsonify({'status': 'error', 'message': 'Missing document'}), 400


    device_id = received_data['fullDocument'].get('ISAAC ID')   # Get the 'ISAAC ID' from the 'fullDocument' field
    if not device_id:
        app.logger.error("Missing 'ISAAC ID' in 'fullDocument'")
        return jsonify({'status': 'error', 'message': 'Missing ISAAC ID'}), 400

    app.logger.info(f"Device ID: {device_id}")
    app.logger.debug(f"Full received data: {received_data}")

    return jsonify({'message': 'Device ID received successfully!', 'device_id': device_id}), 200

def map_value(value, in_min, in_max, out_min, out_max):
    """
    @brief Scale input value from the input range to the output range.
    
    @param value Input value to be mapped.
    @param in_min Minimum of input range.
    @param in_max Maximum of input range.
    @param out_min Minimum of output range.
    @param out_max Maximum of output range.
    
    @return Mapped output value.
    """
    return (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

@app.route('/receiveAQI', methods=['POST'])
def receive_aqi():
    """
    @brief Responds to updates in PM2.5 levels from incoming requests.

    This function receives air quality data (AQI) from a POST request and updates the global state.
    
    @return JSON response indicating success or error status.
    """
    global aqi, new_data

    try:
        latest_sensor_document = request.get_json()
        app.logger.debug("Received data: %s", latest_sensor_document)
    except Exception as e:
        app.logger.error(f"Error parsing JSON: {e}")
        return jsonify({'error': 'Invalid JSON format'}), 400

    if 'fullDocument' not in latest_sensor_document:
        app.logger.error("Missing 'fullDocument' in received data")
        return jsonify({'error': 'Missing document'}), 400

    try:
        aqi = int(latest_sensor_document['fullDocument']['PM2.5'])
        app.logger.info(f"Received AQI: {aqi}")
    except Exception as e:
        app.logger.error(f"Error parsing AQI: {e}")
        return jsonify({'error': 'Invalid AQI value'}), 400
    
    # Send data to MongoDB
    sendDatatoMongoDB()
    return jsonify({'status': 'success'}), 200

# Expects an integer as input and returns a tuple of (red, green, blue) color values
def ledcolor(pm2_5: int) -> tuple[int, int, int]:
    """
    @brief Determine the LED color based on PM2.5 levels.

    @param pm2_5 PM2.5 level used to decide the LED color.
    
    @return Tuple of (red, green, blue) color values.
    """
    if(AQI_MAX > pm2_5 >= THRESHOLD_HIGH):
        return 255, 0, 0  # Red color for high levels
    elif(150 > pm2_5 >= THRESHOLD_MEDIUM):
        return 255, 255, 0  # Yellow color for medium levels
    else:
        return 0,255,0  # Green color for normal levels

def senddatatoMQTTServer(data):
    """
    @brief Send data to the MQTT server.

    @param data Data to be sent to the MQTT server.
    """
    global device_id

    if not device_id:
        app.logger.error("Device ID not set")
        return
    
    if not mqtt_client:
        app.logger.error("MQTT client not connected")
        return
    
    app.logger.debug("Sending data to MQTT server: %s", data)
    topic = f"devices/{device_id}/action_params"
    try:
        mqtt_client.publish(topic, str(data))
        app.logger.info("Data sent to MQTT Server successfully")
    except Exception as e:
        app.logger.error(f"Error sending data to MQTT server: {e}")
        return

def sendDatatoMongoDB() -> None:
    """
    @brief Update the 'action' collection in MongoDB with new data.

    @param dutycycle Current duty cycle value.
    @param status Current status of the system.
    @param red Red component of the LED color.
    @param green Green component of the LED color.
    @param blue Blue component of the LED color.
    """
    global aqi, mode

    with mode_lock:
        current_mode = mode

    if not action_collection:
        app.logger.error("Collection not found")
        return
    
    red, green, blue = ledcolor(aqi)

    if current_mode == "0":
        dutycycle = map_value(aqi, 0, AQI_MAX, 0, DUTY_CYCLE_MAX)
        status = "Normal"
    elif current_mode == "1":
        dutycycle = DUTY_CYCLE_MAX
        status = "Fast"
    elif current_mode == "2":
        dutycycle = DUTY_CYCLE_MIN_WORKING
        status = "Slow"
    elif current_mode == "3":
        dutycycle = DUTY_CYCLE_MIN_IDLE
        status = "Stationary"
    else:
        app.logger.error("Invalid mode")
        return  # Handle invalid mode gracefully

    # Create a document to be inserted into the collection
    document = {
        "DutyCycle": dutycycle,
        "ISAAC_STATUS": status,
        "RED": red,
        "GREEN": green,
        "BLUE": blue
    }
    app.logger.info("Inserting data into MongoDB: %s", document)
    try:
        result = action_collection.insert_one(document)
        app.logger.info(f"Data inserted successfully: {result.inserted_id}")
    except Exception as e:
        app.logger.error(f"Error inserting data into MongoDB: {e}")
        return

    senddatatoMQTTServer(document)




@app.route('/receiveMode', methods=['POST'])
def receive()   -> jsonify:
    """
    @brief Respond to POST requests by receiving the latest mode.

    This function updates the global mode based on incoming webhook payloads.

    mode_lock ensures thread-safe access to the global 'mode' variable,
    preventing race conditions by serializing read and write operations
    across multiple threads. 

    Using 'with' the process of acquiring and releasing the lock is done automatically.
    Once the statements within the with block are executed, the lock is released for other threads to acquire.
    
    @return JSON response indicating success or error status.
    """
    global mode 
    if request.is_json:
        try:
            content = request.get_json()
        except Exception as e:
            app.logger.error(f"Error parsing JSON: {e}")
            return jsonify({'message': 'Invalid JSON format!'}), 400

        app.logger.info("Received data: %s", content)

        print("1")

        if 'fullDocument' not in content:
            app.logger.error("Missing 'fullDocument' in received data")
            return jsonify({'message': 'Missing document'}), 400
        
        received_mode = content['fullDocument'].get('request_mode')
        app.logger.info(f"Received mode: {received_mode}")
    
        if received_mode in valid_modes:
            with mode_lock:
                mode = received_mode
                sendDatatoMongoDB()
            return jsonify({'message': 'Valid mode received. Changing to {}'.format(received_mode)})
        else:
            return jsonify({'message': 'Invalid mode received'})
            
    else:
        return jsonify({'message': 'Invalid data format!'}), 400

    

if __name__ == "__main__":
    # Start the monitoring thread
    '''
    monitor_thread = Thread(target=monitor_mode)
    monitor_thread.daemon = True  # Allow the thread to exit when the main program exits
    monitor_thread.start()
    '''
    app.run(host='0.0.0.0', port=5000, debug=True)
