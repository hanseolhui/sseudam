# Android 1.10.31

- IME insets applied to common Scaffold, consumed content padding to avoid duplicate insets.
- Login coroutine belongs to persistent PlusCard; cancellation no longer shown as a service error.
- Existing Play subscriptions queried before purchase launch. Same-account purchases submitted for verification; other-account purchases receive actionable guidance without another billing flow.
- Account token invalidated on account changes; stale receipt/config responses ignored.
- Server ownership verification remains unchanged. No automatic purchase transfer.
- Play release AAB built; Play and GitHub Kotlin compilation passed.
- 23 unit tests passed, including 4 purchase-account cases. Keyboard geometry and real-device purchase preflight require device verification after Play delivery.
- Previous 1.10.30 test: admin account purchase/restore succeeded. Non-admin account was unsubscribed; Play blocked duplicate purchase because device Play account already owned subscription.
