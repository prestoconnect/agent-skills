<?php

namespace App\Services;

use Illuminate\Support\Facades\Http;

final class PrestoClient
{
    public function init(array $fields): array
    {
        ksort($fields);
        openssl_sign(json_encode($fields), $signature, file_get_contents(base_path('keys/merchant.pem')), OPENSSL_ALGO_SHA256);
        $fields['signature'] = base64_encode($signature);
        return Http::post(config('services.presto.url') . '/payment/init', $fields)->json();
    }
}
