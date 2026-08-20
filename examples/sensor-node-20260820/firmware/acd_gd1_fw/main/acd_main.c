/* Golden Design #1 firmware: 1 Hz LED blink + SHT40 temperature/humidity log.
 * Pin assignments come exclusively from the generated acd_pins.h projection.
 */
#include <stdio.h>

#include "acd_pins.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "acd_gd1";

static i2c_master_dev_handle_t s_sht40;

static void sht40_log_once(void)
{
    const uint8_t measure_cmd = 0xFD; /* high-precision measurement */
    uint8_t raw[6] = {0};
    esp_err_t err = i2c_master_transmit(s_sht40, &measure_cmd, 1, 100);
    if (err == ESP_OK) {
        vTaskDelay(pdMS_TO_TICKS(10));
        err = i2c_master_receive(s_sht40, raw, sizeof(raw), 100);
    }
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "SHT40 read failed: %s", esp_err_to_name(err));
        return;
    }
    int t_ticks = (raw[0] << 8) | raw[1];
    int rh_ticks = (raw[3] << 8) | raw[4];
    float temp_c = -45.0f + 175.0f * (float)t_ticks / 65535.0f;
    float rh = -6.0f + 125.0f * (float)rh_ticks / 65535.0f;
    ESP_LOGI(TAG, "SHT40 temp_c=%.2f rh=%.2f", (double)temp_c, (double)rh);
}

void app_main(void)
{
    ESP_LOGI(TAG, "ACD GD1 fw boot target_revision=%s", ACD_TARGET_REVISION);
    ESP_LOGI(TAG, "pins led=%d sda=%d scl=%d", ACD_PIN_LED, ACD_PIN_I2C_SDA, ACD_PIN_I2C_SCL);

    gpio_config_t led_cfg = {
        .pin_bit_mask = 1ULL << ACD_PIN_LED,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_ERROR_CHECK(gpio_config(&led_cfg));

    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = -1,
        .sda_io_num = ACD_PIN_I2C_SDA,
        .scl_io_num = ACD_PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags = {.enable_internal_pullup = false},
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = ACD_SHT40_I2C_ADDRESS,
        .scl_speed_hz = 100000,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev_cfg, &s_sht40));

    int led_state = 0;
    int since_log_ms = ACD_LOG_PERIOD_MS;
    for (;;) {
        led_state = !led_state;
        gpio_set_level(ACD_PIN_LED, led_state);
        ESP_LOGI(TAG, "LED gpio=%d state=%d", ACD_PIN_LED, led_state);
        if (since_log_ms >= ACD_LOG_PERIOD_MS) {
            sht40_log_once();
            since_log_ms = 0;
        }
        vTaskDelay(pdMS_TO_TICKS(ACD_LED_BLINK_PERIOD_MS / 2));
        since_log_ms += ACD_LED_BLINK_PERIOD_MS / 2;
    }
}
