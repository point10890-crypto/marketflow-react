package com.bitman.marketflow.config;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.databind.JsonSerializer;
import com.fasterxml.jackson.databind.SerializerProvider;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.io.IOException;

@Configuration
public class JacksonConfig {

    @Bean
    public Jackson2ObjectMapperBuilderCustomizer jsonCustomizer() {
        return builder -> {
            builder.serializerByType(Double.class, new SafeDoubleSerializer());
            builder.serializerByType(Float.class, new SafeFloatSerializer());
        };
    }

    private static class SafeDoubleSerializer extends JsonSerializer<Double> {
        @Override
        public void serialize(Double value, JsonGenerator gen, SerializerProvider sp) throws IOException {
            if (value == null || value.isNaN() || value.isInfinite()) {
                gen.writeNull();
            } else {
                gen.writeNumber(value);
            }
        }
    }

    private static class SafeFloatSerializer extends JsonSerializer<Float> {
        @Override
        public void serialize(Float value, JsonGenerator gen, SerializerProvider sp) throws IOException {
            if (value == null || value.isNaN() || value.isInfinite()) {
                gen.writeNull();
            } else {
                gen.writeNumber(value);
            }
        }
    }
}
