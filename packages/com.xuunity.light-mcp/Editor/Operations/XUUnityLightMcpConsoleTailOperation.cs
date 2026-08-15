using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using UnityEngine;
using XUUnity.LightMcp.Editor.Bridge;
using XUUnity.LightMcp.Editor.Core;

namespace XUUnity.LightMcp.Editor.Operations
{
    internal sealed class XUUnityLightMcpConsoleTailOperation : IXUUnityLightMcpOperation
    {
        public const int DefaultMaxPayloadBytes = 16384;
        public const int ConsoleItemByteOverhead = 64;
        public const string ByteBudgetTruncationMarker = "\n[truncated_by_byte_budget]";
        public const string TruncationRecoveryTool = "unity_console_grep";
        public const string TruncationRecoveryHint =
            "Use unity_console_grep with a pattern (same source) to fetch the specific entries compactly.";
        public const string FullPayloadRecoveryHint =
            "Re-run unity_console_tail with maxPayloadBytes=-1 for the unbounded raw tail; raise limit for more items.";

        public string OperationName => "unity.console.tail";

        public XUUnityLightMcpResponse Execute(XUUnityLightMcpRequest request)
        {
            var args = string.IsNullOrWhiteSpace(request.args_json)
                ? new XUUnityLightMcpConsoleTailArgs()
                : JsonUtility.FromJson<XUUnityLightMcpConsoleTailArgs>(request.args_json) ?? new XUUnityLightMcpConsoleTailArgs();

            var source = string.IsNullOrWhiteSpace(args.source) ? "console" : args.source.Trim();
            if (!string.Equals(source, "console", StringComparison.OrdinalIgnoreCase))
            {
                var message = "unity.console.tail in the Unity bridge reads only the in-memory Console buffer. "
                    + "Use the host tool with source=editor_log for Editor.log tail.";
                return XUUnityLightMcpResponseWriter.Error(
                    request.request_id,
                    "unsupported_console_tail_source",
                    message);
            }

            var limit = Math.Max(1, args.limit);
            var includeTypes = NormalizeIncludeTypes(args.includeTypes);

            var allItems = XUUnityLightMcpConsoleBuffer.Snapshot();
            var filtered = allItems.Where(item => includeTypes.Contains(item.type)).ToList();

            var truncated = filtered.Count > limit;
            if (filtered.Count > limit)
            {
                filtered = filtered.Skip(filtered.Count - limit).ToList();
            }

            var budget = ResolveConsoleTailByteBudget(args.maxPayloadBytes);
            var bounded = ApplyConsoleTailByteBudget(
                filtered,
                budget,
                out var itemsDroppedForByteBudget,
                out var newestItemTruncated,
                out var payloadBytesEstimate);
            var byteBudgetTruncated = itemsDroppedForByteBudget > 0 || newestItemTruncated;

            var tailCaveat = "Unity Console tail reads the in-memory Console buffer, which may be stale "
                + "after clear-on-play or ring-buffer eviction; use source=editor_log for compile-error validation.";
            var payload = new XUUnityLightMcpConsoleTailBoundedPayload
            {
                project_root = XUUnityLightMcpFileIpcPaths.ProjectRootPath,
                source = "console",
                items = bounded,
                truncated = truncated,
                result_trust_class = "console_buffer_may_be_stale",
                console_tail_caveat = tailCaveat,
                recommended_next_action = "use_source_editor_log_for_compile_errors",
                max_payload_bytes = budget,
                payload_bytes_estimate = payloadBytesEstimate,
                byte_budget_truncated = byteBudgetTruncated,
                items_dropped_for_byte_budget = itemsDroppedForByteBudget,
                newest_item_truncated = newestItemTruncated,
                byte_budget_enforced_by = "unity_bridge"
            };
            if (byteBudgetTruncated || truncated)
            {
                payload.truncation_recovery_tool = TruncationRecoveryTool;
                payload.truncation_recovery_hint = TruncationRecoveryHint;
                payload.full_payload_recovery_hint = FullPayloadRecoveryHint;
            }

            return XUUnityLightMcpResponseWriter.Success(
                request.request_id,
                OperationName,
                JsonUtility.ToJson(payload)
            );
        }

        internal static int ResolveConsoleTailByteBudget(int requested)
        {
            if (requested < 0)
            {
                return -1;
            }
            return requested == 0 ? DefaultMaxPayloadBytes : requested;
        }

        internal static int EstimateConsoleItemBytes(XUUnityLightMcpConsoleItem item)
        {
            if (item == null)
            {
                return ConsoleItemByteOverhead;
            }
            return Utf8Length(item.type)
                + Utf8Length(item.message)
                + Utf8Length(item.timestamp)
                + Utf8Length(item.stack_trace)
                + ConsoleItemByteOverhead;
        }

        internal static List<XUUnityLightMcpConsoleItem> ApplyConsoleTailByteBudget(
            List<XUUnityLightMcpConsoleItem> items,
            int budget,
            out int itemsDroppedForByteBudget,
            out bool newestItemTruncated,
            out int payloadBytesEstimate)
        {
            itemsDroppedForByteBudget = 0;
            newestItemTruncated = false;
            payloadBytesEstimate = 0;

            var source = items ?? new List<XUUnityLightMcpConsoleItem>();
            if (budget < 0)
            {
                payloadBytesEstimate = source.Sum(EstimateConsoleItemBytes);
                return source;
            }

            var keptFromIndex = source.Count;
            var runningBytes = 0;
            for (var index = source.Count - 1; index >= 0; index--)
            {
                var itemBytes = EstimateConsoleItemBytes(source[index]);
                if (runningBytes + itemBytes > budget)
                {
                    break;
                }
                runningBytes += itemBytes;
                keptFromIndex = index;
            }

            if (keptFromIndex >= source.Count && source.Count > 0)
            {
                var truncatedNewest = TruncateItemToBudget(source[source.Count - 1], budget);
                itemsDroppedForByteBudget = source.Count - 1;
                newestItemTruncated = true;
                payloadBytesEstimate = EstimateConsoleItemBytes(truncatedNewest);
                return new List<XUUnityLightMcpConsoleItem> { truncatedNewest };
            }

            itemsDroppedForByteBudget = keptFromIndex;
            payloadBytesEstimate = runningBytes;
            return source.Skip(keptFromIndex).ToList();
        }

        static XUUnityLightMcpConsoleItem TruncateItemToBudget(XUUnityLightMcpConsoleItem item, int budget)
        {
            var clone = new XUUnityLightMcpConsoleItem
            {
                type = item?.type ?? "unknown",
                message = item?.message ?? "",
                timestamp = item?.timestamp ?? "",
                stack_trace = ""
            };
            var fixedBytes = Utf8Length(clone.type)
                + Utf8Length(clone.timestamp)
                + Utf8Length(ByteBudgetTruncationMarker)
                + ConsoleItemByteOverhead;
            var availableForMessage = Math.Max(0, budget - fixedBytes);
            if (Utf8Length(clone.message) > availableForMessage)
            {
                clone.message = TruncateUtf8(clone.message, availableForMessage);
            }
            clone.message += ByteBudgetTruncationMarker;
            return clone;
        }

        internal static string TruncateUtf8(string value, int maxBytes)
        {
            if (string.IsNullOrEmpty(value) || maxBytes <= 0)
            {
                return "";
            }
            if (Utf8Length(value) <= maxBytes)
            {
                return value;
            }
            var low = 0;
            var high = Math.Min(value.Length, maxBytes);
            while (low < high)
            {
                var middle = (low + high + 1) / 2;
                if (Utf8Length(value.Substring(0, middle)) <= maxBytes)
                {
                    low = middle;
                }
                else
                {
                    high = middle - 1;
                }
            }
            return value.Substring(0, low);
        }

        static int Utf8Length(string value)
        {
            return string.IsNullOrEmpty(value) ? 0 : Encoding.UTF8.GetByteCount(value);
        }

        static HashSet<string> NormalizeIncludeTypes(string[] includeTypes)
        {
            if (includeTypes == null || includeTypes.Length == 0)
            {
                return new HashSet<string>(new[] { "error", "warning", "log", "exception" }, StringComparer.OrdinalIgnoreCase);
            }

            return new HashSet<string>(includeTypes.Where(value => !string.IsNullOrWhiteSpace(value)), StringComparer.OrdinalIgnoreCase);
        }
    }
}
