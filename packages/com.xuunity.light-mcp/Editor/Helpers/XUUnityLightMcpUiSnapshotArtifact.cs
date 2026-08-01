using System;
using System.IO;
using UnityEngine;
using XUUnity.LightMcp.Editor.Core;

namespace XUUnity.LightMcp.Editor.Helpers
{
    /// <summary>
    /// Writes a ui.read.v1 snapshot beside the capture it describes. The comparison surface consumes a
    /// snapshot by path, so a snapshot returned inline only can never close the semantic lane.
    /// </summary>
    internal static class XUUnityLightMcpUiSnapshotArtifact
    {
        public static string Write(
            XUUnityLightMcpUiTreePayload snapshot,
            string requestedPath,
            string companionPath,
            string fallbackName,
            out XUUnityLightMcpUiDiagnostic error)
        {
            error = null;
            if (snapshot == null)
            {
                return "";
            }

            try
            {
                var outputPath = ResolvePath(requestedPath, companionPath, fallbackName);
                XUUnityLightMcpAtomicFileWriter.WriteAllText(outputPath, JsonUtility.ToJson(snapshot));
                return outputPath;
            }
            catch (Exception exception)
            {
                error = XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "ui_snapshot_not_written",
                    "The ui.read.v1 snapshot could not be persisted, so the semantic acceptance lane has no input.",
                    exception.Message);
                return "";
            }
        }

        static string ResolvePath(string requestedPath, string companionPath, string fallbackName)
        {
            var requested = (requestedPath ?? "").Trim();
            if (!string.IsNullOrEmpty(requested))
            {
                return Path.IsPathRooted(requested)
                    ? requested
                    : Path.GetFullPath(Path.Combine(XUUnityLightMcpFileIpcPaths.ProjectRootPath, requested));
            }

            var companion = (companionPath ?? "").Trim();
            if (!string.IsNullOrEmpty(companion))
            {
                var directory = Path.GetDirectoryName(companion);
                var stem = Path.GetFileNameWithoutExtension(companion);
                return Path.Combine(
                    string.IsNullOrEmpty(directory) ? "." : directory,
                    stem + XUUnityLightMcpUiRead.SnapshotArtifactSuffix);
            }

            XUUnityLightMcpFileIpcPaths.EnsureDirectories();
            var stamp = DateTime.UtcNow.ToString("yyyyMMddTHHmmssZ");
            return Path.Combine(
                XUUnityLightMcpFileIpcPaths.CapturesDirectory,
                $"{fallbackName}-{stamp}{XUUnityLightMcpUiRead.SnapshotArtifactSuffix}");
        }
    }
}
