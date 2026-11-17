#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <math.h>
#include "wifi_secrets.h"

static constexpr int SDA_PIN = 21;
static constexpr int SCL_PIN = 22;
static constexpr uint32_t SAMPLE_INTERVAL_MS = 5000;
static constexpr uint32_t WIFI_RETRY_MS = 10000;
static constexpr char API_URL[] = "http://172.16.0.188:8000/api/sensors/data";

static uint8_t sensorAddress = 0;
static uint32_t lastSampleMs = 0;
static uint32_t lastWifiAttemptMs = 0;

static bool probe(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

static bool initializeSensor() {
  sensorAddress = probe(0x23) ? 0x23 : (probe(0x5C) ? 0x5C : 0);
  if (!sensorAddress) return false;

  Wire.beginTransmission(sensorAddress);
  Wire.write(0x01);  // power on
  if (Wire.endTransmission() != 0) {
    sensorAddress = 0;
    return false;
  }
  delay(10);
  Wire.beginTransmission(sensorAddress);
  Wire.write(0x07);  // reset data register
  if (Wire.endTransmission() != 0) {
    sensorAddress = 0;
    return false;
  }
  delay(10);
  Serial.printf("BH1750 ready at 0x%02X on SDA=%d SCL=%d\n", sensorAddress, SDA_PIN, SCL_PIN);
  return true;
}

static bool readLux(float &lux, uint16_t &raw) {
  if (sensorAddress == 0 && !initializeSensor()) return false;

  // Request a fresh one-shot, high-resolution conversion.
  Wire.beginTransmission(sensorAddress);
  Wire.write(0x20);
  if (Wire.endTransmission() != 0) return false;
  delay(180);

  const size_t received = Wire.requestFrom(sensorAddress, static_cast<uint8_t>(2));
  if (received < 2 || Wire.available() < 2) {
    while (Wire.available()) Wire.read();
    return false;
  }
  raw = (static_cast<uint16_t>(Wire.read()) << 8) | Wire.read();
  lux = raw / 1.2f;
  return isfinite(lux) && lux >= 0.0f && lux <= 120000.0f;
}

static void maintainWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  const uint32_t now = millis();
  if (now - lastWifiAttemptMs < WIFI_RETRY_MS) return;
  lastWifiAttemptMs = now;

  if (WIFI_SSID[0] == '\0' || WIFI_PASSWORD[0] == '\0') {
    Serial.println("Wi-Fi credentials missing; create wifi_secrets.h from the example file");
    return;
  }

  Serial.println("Connecting to configured Wi-Fi...");
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

static void sendReading(float lux, uint16_t raw) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("Wi-Fi offline; sample held locally only: %.2f lx (raw=%u)\n", lux, raw);
    return;
  }

  WiFiClient client;
  HTTPClient http;
  http.setTimeout(4000);
  if (!http.begin(client, API_URL)) {
    Serial.println("Could not open VM API connection");
    return;
  }
  http.addHeader("Content-Type", "application/json");
  char payload[192];
  snprintf(payload, sizeof(payload),
           "{\"node\":\"light-esp32\",\"light_lux\":%.2f,\"source\":\"real\"}",
           lux);
  const int status = http.POST(reinterpret_cast<uint8_t *>(payload), strlen(payload));
  Serial.printf("Light %.2f lx (raw=%u); VM POST status=%d\n", lux, raw, status);
  http.end();
}

void setup() {
  Serial.begin(9600);
  delay(300);
  Wire.begin(SDA_PIN, SCL_PIN, 100000);
  Serial.println("SolarTwin light node starting (BH1750 -> Wi-Fi -> VM API)");
  initializeSensor();
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastWifiAttemptMs = millis();
}

void loop() {
  maintainWiFi();
  const uint32_t now = millis();
  if (now - lastSampleMs < SAMPLE_INTERVAL_MS) {
    delay(20);
    return;
  }
  lastSampleMs = now;

  float lux = 0.0f;
  uint16_t raw = 0;
  if (!readLux(lux, raw)) {
    Serial.println("BH1750 measurement failed; checking sensor again next cycle");
    sensorAddress = 0;
    return;
  }
  sendReading(lux, raw);
}
