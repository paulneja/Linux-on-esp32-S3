idf_component_register(SRCS "uc-rv32ima.c"
			"cache.c"
			"port-esp.c"
			"net_console.c"
		       LDFRAGMENTS "link.lf"
		       INCLUDE_DIRS "."
		       REQUIRES esp_wifi esp_netif esp_event nvs_flash lwip
				esp_timer esp_partition esp_psram esp_hw_support
				hal soc driver spi_flash)
