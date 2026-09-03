using System;

namespace XUUnity.LightMcp.Editor.ScenarioHooks
{
    [Serializable]
    public sealed class XUUnityLightMcpMutationDelta
    {
        public const string SchemaVersion = "xuunity.mutation-delta.v1";

        public string schema_version = SchemaVersion;
        public string unit = "";
        public string target = "";
        public int before_count;
        public int after_count;
        public int added_count;
        public int removed_count;
        public int changed_count;

        public static XUUnityLightMcpMutationDelta Create(
            string unit,
            string target,
            int beforeCount,
            int afterCount,
            int addedCount,
            int removedCount,
            int changedCount)
        {
            if (string.IsNullOrWhiteSpace(unit))
            {
                throw new ArgumentException("Mutation delta unit is required.", nameof(unit));
            }

            if (string.IsNullOrWhiteSpace(target))
            {
                throw new ArgumentException("Mutation delta target is required.", nameof(target));
            }

            if (beforeCount < 0 || afterCount < 0 || addedCount < 0 || removedCount < 0 || changedCount < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(beforeCount), "Mutation delta counts cannot be negative.");
            }

            if (afterCount != beforeCount + addedCount - removedCount)
            {
                throw new ArgumentException(
                    "Mutation delta counts must satisfy afterCount = beforeCount + addedCount - removedCount.");
            }

            return new XUUnityLightMcpMutationDelta
            {
                unit = unit.Trim(),
                target = target.Trim(),
                before_count = beforeCount,
                after_count = afterCount,
                added_count = addedCount,
                removed_count = removedCount,
                changed_count = changedCount
            };
        }
    }
}
