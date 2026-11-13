namespace Silfy.Core.Subscriptions;

public enum SubscriptionTier { Free, Premium }

public enum PremiumFeature
{
    ThemeSelection,
    AdditionalVoices,
    DesktopCompanion,
    CustomCommands
}

public sealed record SubscriptionEntitlements(SubscriptionTier Tier)
{
    public bool Has(PremiumFeature feature) => Tier == SubscriptionTier.Premium;
}
