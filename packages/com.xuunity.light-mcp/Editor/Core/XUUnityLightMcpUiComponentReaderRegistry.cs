using System;
using System.Collections.Generic;
using UnityEngine;

namespace XUUnity.LightMcp.Editor.Core
{
    internal interface IXUUnityLightMcpUiComponentReader
    {
        string BackendId { get; }

        bool TryDescribe(Component component, XUUnityLightMcpUiNode node);
    }

    internal static class XUUnityLightMcpUiComponentReaderRegistry
    {
        static readonly List<IXUUnityLightMcpUiComponentReader> Readers = new();

        public static bool HasReaders => Readers.Count > 0;

        public static void Register(IXUUnityLightMcpUiComponentReader reader)
        {
            if (reader == null || string.IsNullOrWhiteSpace(reader.BackendId))
            {
                return;
            }

            for (var i = 0; i < Readers.Count; i++)
            {
                if (string.Equals(Readers[i].BackendId, reader.BackendId, StringComparison.Ordinal))
                {
                    Readers[i] = reader;
                    return;
                }
            }

            Readers.Add(reader);
        }

        public static List<string> BackendIds()
        {
            var ids = new List<string>(Readers.Count);
            foreach (var reader in Readers)
            {
                ids.Add(reader.BackendId);
            }

            return ids;
        }

        public static bool Describe(Component component, XUUnityLightMcpUiNode node)
        {
            if (component == null || node == null)
            {
                return false;
            }

            var described = false;
            foreach (var reader in Readers)
            {
                if (!reader.TryDescribe(component, node))
                {
                    continue;
                }

                described = true;
                if (string.IsNullOrEmpty(node.component_detail_backend))
                {
                    node.component_detail_backend = reader.BackendId;
                }
            }

            return described;
        }
    }
}
