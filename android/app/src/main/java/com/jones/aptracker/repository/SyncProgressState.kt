package com.jones.aptracker.repository

data class SyncProgressState(
    val isSyncing: Boolean = false,
    val loopsCompleted: Int = 0,
    val itemsFetchedInSync: Int = 0,
    val totalDeltaToFetch: Int = 0,
    val progressPercentage: Int = 0,
    val serverReportedTotalItems: Int = 0,
    val localItemCount: Int = 0,
    val hasPendingBackfill: Boolean = false,
    val isJustCompleted: Boolean = false
)
