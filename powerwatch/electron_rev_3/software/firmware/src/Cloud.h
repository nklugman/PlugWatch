/**
 * Cloud Interface.
 */

#pragma once

#include <Particle.h>

#define ERROR_EVENT "!"

//Adding a G for a particle cloud webhook
//a webhook only matches on prefix, so all G gets set
//to one chain, and all ! get sent to another chain
#define CHARGE_STATE_EVENT "gc"
#define HEARTBEAT_EVENT "gh"
#define IMU_EVENT "gi"
#define IMU_ERROR_EVENT "!i"
#define LIGHT_EVENT "gl"
#define NRFWIT_EVENT "n"

#define WIFI_SCAN_EVENT "gw"
#define WIFI_ERROR_EVENT "!w"
#define AUDIO_EVENT "ga"
#define AUDIO_ERROR_EVENT "!a"
#define GPS_EVENT "gt"

#define SD_ERROR_EVENT "!s"
#define SD_READ_EVENT "gsa"
#define SD_REBOOT_EVENT "gsb"
#define SD_QUERY_EVENT "gsc"
#define SD_DELETE_EVENT "gsd"

#define SMS_EVENT "gy"

class Cloud {
public:
  static void setup();
  static void Publish(String tag, String message);
};