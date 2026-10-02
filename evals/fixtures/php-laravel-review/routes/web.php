<?php

use App\Http\Controllers\PrestoWebhookController;
use Illuminate\Support\Facades\Route;

Route::post('/presto/notify', PrestoWebhookController::class);
