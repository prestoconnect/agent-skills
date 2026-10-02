package com.acme.admin;

import com.prestouniverse.pay.PrestoPayClient;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class PrestoConfig {
    @Bean
    PrestoPayClient prestoPayClient() {
        return PrestoPayClient.fromEnv();
    }
}
