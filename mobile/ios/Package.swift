// swift-tools-version: 5.9
import PackageDescription

// Offline purchase-contract regressions, independent of StoreKit and app/user data.
let package = Package(
    name: "SseudamPurchasePolicy",
    products: [.library(name: "SseudamPurchasePolicy", targets: ["SseudamPurchasePolicy"])],
    targets: [
        .target(name: "SseudamPurchasePolicy", path: "Sseudam/PurchasePolicy", sources: ["PurchaseConfiguration.swift", "SubscriptionPriceSummary.swift"]),
        .testTarget(name: "SseudamPurchasePolicyTests", dependencies: ["SseudamPurchasePolicy"], path: "Tests")
    ]
)
