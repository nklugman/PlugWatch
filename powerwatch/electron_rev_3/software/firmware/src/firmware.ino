/*
 * Project sensor_board_v2
 * Description: For Q2 2018 Deployment in Ghana
 * Author: Noah Klugman; Pat Pannuto
 */

// Native
#include <Particle.h>

// Third party libraries
#include <CellularHelper.h>

// Our code
#include "ChargeState.h"
#include "SMS.h"
#include "Cloud.h"
#include "FileLog.h"
#include "Gps.h"
#include "ESP8266.h"
#include "Wifi.h"
#include "Heartbeat.h"
#include "Imu.h"
#include "Light.h"
#include "NrfWit.h"
#include "SDCard.h"
#include "Subsystem.h"
#include "firmware.h"


//***********************************
//* TODO's
//***********************************

//System
//  State Machine refactor
//    remove timers?
//    remove threads
//    think about on-event actions (do we do at all? do we keep a buffer?)
//  Merge in Matt's branch
//  Sanity check cloud commands // controls. Minimize them. Document.
//  Integrate with the publish manager (maybe not a concern anymore?)
//  Figure out what to do with system events
//  figure out when to go to safe mode
//  control the debug light
//  add in periodic reset
//Peripherals
//  add temp alone
//  make wifi syncronus
//  wifi ssid cloud hashing
//  write audio transfer
//  APN libraries / switches
//  Add unique ID chip
//SD
//  add delete (maybe not?)
//  add format (maybe not?)
//  check powercycle
//  add upload file, upload all
//Default Heartbeat Packet
//  size of free mem on SD Card (maybe not?)
//  system mem
//  temp
//  cellular strength
//  system count (retained)
//  software version (maybe not?)
//  isCharging
//  num heartbeat (retained)
//Identity Packet (daily?)
//  IMEI
//  ICCID
//  Cape ID
//  SD Card name
//  Last GPS
//  WiT MAC
//  System Count
//Heartbeat Stretch goals
//  SMS Heartbeat
//    disable on particle apn
//    figure out endpoint
//  Heartbeat on certain system events (upgrade in specific)
//Tests
//  SD works without cellular
//  Cellular works without SD
//  Device comes back from dead battery
//  Cross validate wits, temp, light, audio?
//Random ideas
//  Can we run on 0.8.0?

//***********************************
//* Critical System Config
//***********************************
int version_num = 2; //hack
PRODUCT_ID(7456); //US testbed
PRODUCT_VERSION(2);
SYSTEM_THREAD(ENABLED);
STARTUP(System.enableFeature(FEATURE_RESET_INFO));
STARTUP(System.enableFeature(FEATURE_RETAINED_MEMORY));
//STARTUP(cellular_sms_received_handler_set(smsRecvFlag, NULL, NULL)); //TODO this needs to be added for SMS


//ArduinoOutStream cout(Serial);
STARTUP(cellular_credentials_set("http://mtnplay.com.gh", "", "", NULL));
SYSTEM_MODE(MANUAL);
bool handshake_flag = false;

//**********************************
//* Pin Configuration
//**********************************
int reset_btn = A0;

//**********************************
//* Allow all peripherals to be run on event
//**********************************
bool power_state_change_flag = false;

//***********************************
//* Watchdogs
//***********************************
const int HARDWARE_WATCHDOG_TIMEOUT_MS = 1000 * 60;
ApplicationWatchdog wd(HARDWARE_WATCHDOG_TIMEOUT_MS, soft_watchdog_reset);
retained int system_cnt;

//***********************************
//* SD Card
//***********************************
SDCard SD;

//***********************************
//* ESP8266 WIFI Module
//***********************************
String serial5_response;
bool serial5_recv_done;
auto esp8266 = ESP8266(&serial5_response, &serial5_recv_done);

//***********************************
//* Reset Monitor
//***********************************
class Reset: public Subsystem {
  typedef Subsystem super;
  using Subsystem::Subsystem;

  // Defer this to the `loop` method so the cloud will get the ACK
  bool reset_flag = false;

  String cloudFunctionName() { return "reset"; }
  int cloudCommand(String command) {
    // Escape hatch if things are really borked
    if (command == "hard") {
      System.reset();
    }
    reset_flag = true;
    return 0;
  }

public:
  void loop() {
    super::loop();
    if (reset_flag) {
      log.append("resetting");
      System.reset();
    }
  }
};

auto resetSubsystem = Reset(SD, "reset_log.txt");

//***********************************
//* Time Sync
//*
//* Particle synchronizes its clock when it first connects. Over time, it will
//* drift away from real time. This routine will re-sync local time.
//***********************************
const int TWELVE_HOURS = 1000 * 60 * 60 * 12;

class TimeSync: public Subsystem {
  typedef Subsystem super;
  using Subsystem::Subsystem;

  String cloudFunctionName() { return "timeSync"; }
  int cloudCommand(String command) {
    if (command == "now") {
      sync();
    }
    return 0;
  }

  void sync() {
    if (! Particle.syncTimePending()) { // if not currently syncing
      unsigned long now = millis();
      unsigned long last = Particle.timeSyncedLast();

      if ((now - last) > TWELVE_HOURS) { // been a while
        log.append("now " + String(now) + ", last sync " + String(last));
        Particle.syncTime(); // kick off a sync
      }
    }
  }

public:
  void loop() {
    sync();
  }
};

auto timeSyncSubsystem = TimeSync(SD, "time_sync.txt");

//***********************************
//* Heartbeat
//***********************************
retained int HEARTBEAT_FREQUENCY = Heartbeat::DEFAULT_FREQ;
retained int HEARTBEAT_COUNT = 0;
auto heartbeatSubsystem = Heartbeat(SD, &HEARTBEAT_FREQUENCY, &HEARTBEAT_COUNT);

//***********************************
//* Charge state
//***********************************
retained int CHARGE_STATE_FREQUENCY = ChargeState::DEFAULT_FREQ;
auto chargeStateSubsystem = ChargeState(SD, &CHARGE_STATE_FREQUENCY);

//***********************************
//* IMU
//***********************************
retained int IMU_FREQUENCY = Imu::DEFAULT_FREQ;
retained int IMU_SAMPLE_COUNT = Imu::DEFAULT_SAMPLE_COUNT;
retained int IMU_SAMPLE_RATE = Imu::DEFAULT_SAMPLE_RATE_MS;
auto imuSubsystem = Imu(SD, &IMU_FREQUENCY, &IMU_SAMPLE_COUNT, &IMU_SAMPLE_RATE);

//***********************************
//* LIGHT
//***********************************
retained int LIGHT_FREQUENCY = Light::DEFAULT_FREQ;
retained float LIGHT_LUX = 0;
auto lightSubsystem = Light(SD, &LIGHT_FREQUENCY, &LIGHT_LUX);

//***********************************
//* NrfWit
//***********************************
auto nrfWitSubsystem = NrfWit(SD);

//***********************************
//* WIFI
//***********************************
retained int WIFI_FREQUENCY = Wifi::DEFAULT_FREQ;
auto wifiSubsystem = Wifi(SD, esp8266, &WIFI_FREQUENCY, &serial5_response, &serial5_recv_done);

//***********************************
//* GPS
//***********************************
retained int GPS_FREQUENCY = Gps::DEFAULT_FREQ;
auto gpsSubsystem = Gps(SD, &GPS_FREQUENCY);

//***********************************
//* SMS
//***********************************
retained int SMS_FREQUENCY = SMS::DEFAULT_FREQ;
auto SMSSubsystem = SMS(SD, &SMS_FREQUENCY);

 //***********************************
 //* CLOUD FUNCTIONS
 //***********************************
 // Legacy functions
 int get_soc(String c) { //cloudfunction
     return (int)(FuelGauge().getSoC());
 }

 int get_battv(String c) { //cloudfunction
     return (int)(100 * FuelGauge().getVCell());
 }


//***********************************
//* System Events
//***********************************
// Not sure if we want to do anything with these in the long run, but for now
// just keep track of everything that happens
auto EventLog = FileLog(SD, "event_log.txt");

String SYSTEM_EVENT = "s";
retained int system_event_count = 0;
retained String last_system_event_time = "";
retained int last_system_event_type = -999;
retained int num_reboots = 0;
retained int num_manual_reboots = 0;

void system_events_setup() {
  Particle.variable("d", system_event_count);
  Particle.variable("e", last_system_event_time);
  Particle.variable("f", last_system_event_type);
  Particle.variable("m", num_manual_reboots);
  Particle.variable("w", num_reboots);
}

void handle_all_system_events(system_event_t event, int param) {
  system_event_count++;
  Serial.printlnf("got event %d with value %d", event, param);
  String system_event_str = String((int)event) + "|" + String(param);
  String time_str = String(Time.format(Time.now(), TIME_FORMAT_ISO8601_FULL));
  last_system_event_time = time_str;
  last_system_event_type = param;
  Cloud::Publish(SYSTEM_EVENT, system_event_str);
  EventLog.append(system_event_str);
}

void system_reset_to_safemode() {
  num_manual_reboots++;
  Cloud::Publish(SYSTEM_EVENT, "manual reboot"); //TODO test if this hangs
  System.enterSafeMode();
}

int force_handshake(String cmd) {
  handshake_flag = true;
  return 0;
}

//***********************************
//* ye-old Arduino
//***********************************
void setup() {
  // if (System.resetReason() == RESET_REASON_PANIC) {
  //   System.enterSafeMode();
  // }

  // Some legacy bits that I'm not sure what we want to do with
  num_reboots++;
  Particle.variable("r", num_reboots);
  Particle.variable("v", String(System.version().c_str()));
  Particle.function("soc",get_soc);
  Particle.function("battv",get_battv);
  Particle.function("handshake", force_handshake);

  // Set up debugging UART
  Serial.begin(9600);
  Serial.println("Initial Setup.");

  // Set up I2C
  Wire.begin();

  // For now, just grab everything that happens and log about it
  // https://docs.particle.io/reference/firmware/photon/#system-events
  System.on(all_events, handle_all_system_events);


  // Get the reset button going
  pinMode(reset_btn, INPUT);
  attachInterrupt(reset_btn, system_reset_to_safemode, RISING, 3);


  // Setup SD card first so that other setups can log
  SD.setup();
  delay(100);

  system_events_setup();

  resetSubsystem.setup();
  timeSyncSubsystem.setup();
  heartbeatSubsystem.setup();
  chargeStateSubsystem.setup();
  //imuSubsystem.setup();
  //lightSubsystem.setup();
  //nrfWitSubsystem.setup();
  gpsSubsystem.setup();
  wifiSubsystem.setup();
  FuelGauge().quickStart();

  LEDStatus status;
  status.off();

  Particle.connect();

  Serial.println("Setup complete.");
}

void loop() {

  if (System.updatesPending())
  {
    int ms = millis();
    while(millis()-ms < 60000) Particle.process();
  }

  if (handshake_flag) {
  handshake_flag = false;
  Particle.publish("spark/device/session/end", "", PRIVATE);
  }


  // Allow particle to do any processing
  // https://docs.particle.io/reference/firmware/photon/#manual-mode
  if (Particle.connected()) {
    Particle.process();
  } else {
    // Don't attempt to connect too frequently as connection attempts hang MY_DEVICES
    static int last_connect_time = 0;
    const int connect_interval_sec = 60;
    int now = Time.now(); // unix time

    if ((last_connect_time == 0) || (now-last_connect_time > connect_interval_sec)) {
      last_connect_time = now;
      Particle.connect();
    }
  }

  static bool once = false;
  if (!once && Particle.connected()) {
         Particle.keepAlive(30); // send a ping every 30 seconds
         once = true;
  }

  if (power_state_change_flag) {
    //imuSubsystem.run();
    //lightSubsystem.run();
    //nrfWitSubsystem.run();
    //gpsSubsystem.run();
    //wifiSubsystem.run();
    //esp8266.run();
    //log.debug("calling peripherals");
    power_state_change_flag = false;
  }



  SD.loop();
  resetSubsystem.loop();
  timeSyncSubsystem.loop();
  heartbeatSubsystem.loop();
  chargeStateSubsystem.loop();
  //imuSubsystem.loop();
  //lightSubsystem.loop();
  //nrfWitSubsystem.loop();
  gpsSubsystem.loop();
  wifiSubsystem.loop();
  esp8266.loop();

  //Call the automatic watchdog
  wd.checkin();

  system_cnt++;
}

void soft_watchdog_reset() {
  //reset_flag = true; //let the reset subsystem shutdown gracefully
  //TODO change to system reset after a certain number of times called
  System.reset();
}

void id() {
  byte i;           // This is for the for loops
  boolean present;  // device present varj
  byte data[8];     // container for the data from device
  byte crc_calc;    //calculated CRC
  byte crc_byte;    //actual CRC as sent by DS2401
  //1-Wire bus reset, needed to start operation on the bus,
  //returns a 1/TRUE if presence pulse detected
  present = ds.reset();
  if (present == TRUE)
  {
    ds.write(0x33);  //Send Read data command
    data[0] = ds.read();
    Serial.print("Family code: 0x");
    PrintTwoDigitHex (data[0], 1);
    Serial.print("Hex ROM data: ");
    for (i = 1; i <= 6; i++)
    {
      data[i] = ds.read(); //store each byte in different position in array
      PrintTwoDigitHex (data[i], 0);
      Serial.print(" ");
    }
    Serial.println();
    crc_byte = ds.read(); //read CRC, this is the last byte
    crc_calc = OneWire::crc8(data, 7); //calculate CRC of the data
    Serial.print("Calculated CRC: 0x");
    PrintTwoDigitHex (crc_calc, 1);
    Serial.print("Actual CRC: 0x");
    PrintTwoDigitHex (crc_byte, 1);
  }
  else //Nothing is connected in the bus
  {
    Serial.println("xxxxx Nothing connected xxxxx");
  }
}