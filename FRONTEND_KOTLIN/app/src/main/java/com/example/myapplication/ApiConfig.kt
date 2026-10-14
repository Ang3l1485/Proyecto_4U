package com.example.myapplication

/**
 * Central place to configure the CLIP API endpoint.
 * After deploying, run:  bash ecs/get_ip.sh
 * Then paste the IP below.
 */
object ApiConfig {
    private const val HOST = "3.129.14.3"
    const val BASE_URL = "http://$HOST:8080"
    const val PREDICT_URL = "$BASE_URL/predict"
}