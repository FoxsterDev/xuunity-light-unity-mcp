using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEditor.PackageManager;
using UnityEditor.PackageManager.Requests;
using UnityEngine;
using XUUnity.LightMcp.Editor.Bridge;
using XUUnity.LightMcp.Editor.Core;
using PackageInfo = UnityEditor.PackageManager.PackageInfo;

namespace XUUnity.LightMcp.Editor.Batch
{
    public static class XUUnityLightMcpBatchPackageRestoreCli
    {
        const string ResultFileArg = "--xuunity-result-file";
        const string StableIdleTicksArg = "--xuunity-package-stable-idle-ticks";
        const string RunIdArg = "--xuunity-package-restore-run-id";
        const string SchemaVersion = "xuunity.sdk-package-restore.v1";

        [Serializable]
        sealed class PackageRecord
        {
            public string name = "";
            public string version = "";
            public string package_id = "";
            public string source = "";
            public bool direct_dependency;
        }

        [Serializable]
        sealed class DependencyXmlRecord
        {
            public string path = "";
            public string sha256 = "";
            public long size_bytes;
        }

        [Serializable]
        sealed class PackageRestoreResult
        {
            public string schema_version = SchemaVersion;
            public string operation = "unity.sdk.package_restore";
            public string run_id = "";
            public string project_root = "";
            public string outcome = "package_restore_failed";
            public string completion_basis = "batchmode_startup_resolve_then_stable_registered_graph";
            public string restore_trigger = "unity_batchmode_project_open";
            public string request_status = "pending";
            public bool succeeded;
            public bool decision_ready;
            public int stable_idle_ticks_required;
            public int stable_idle_ticks_observed;
            public string manifest_sha256 = "";
            public string packages_lock_sha256 = "";
            public PackageRecord[] packages = Array.Empty<PackageRecord>();
            public string[] direct_dependencies = Array.Empty<string>();
            public string[] missing_direct_dependencies = Array.Empty<string>();
            public DependencyXmlRecord[] dependency_xml_sources = Array.Empty<DependencyXmlRecord>();
            public string top_actionable_error = "";
            public string exception_message = "";
            public string started_at_utc = "";
            public string completed_at_utc = "";
            public double duration_seconds;
        }

        static DateTime _startedAtUtc;
        static string _resultFile = "";
        static int _stableIdleTicksRequired = 2;
        static int _stableIdleTicksObserved;
        static ListRequest _listRequest;
        static PackageRestoreResult _result;

        public static void ExecuteFromCommandLine()
        {
            _startedAtUtc = DateTime.UtcNow;
            _resultFile = ReadArg(Environment.GetCommandLineArgs(), ResultFileArg);
            _stableIdleTicksRequired = ParseStableIdleTicks(
                ReadArg(Environment.GetCommandLineArgs(), StableIdleTicksArg));
            _stableIdleTicksObserved = 0;
            _result = new PackageRestoreResult
            {
                run_id = ReadArg(Environment.GetCommandLineArgs(), RunIdArg),
                project_root = XUUnityLightMcpFileIpcPaths.ProjectRootPath,
                stable_idle_ticks_required = _stableIdleTicksRequired,
                started_at_utc = _startedAtUtc.ToString("yyyy-MM-ddTHH:mm:ssZ")
            };

            if (string.IsNullOrWhiteSpace(_result.run_id))
            {
                CompleteFailure("package_restore_run_id_missing", new InvalidOperationException(
                    $"{RunIdArg} is required."));
                return;
            }

            try
            {
                _listRequest = Client.List(false, true);
                _result.request_status = "package_list_requested";
                EditorApplication.update -= Tick;
                EditorApplication.update += Tick;
            }
            catch (Exception ex)
            {
                CompleteFailure("package_list_request_failed", ex);
            }
        }

        static void Tick()
        {
            try
            {
                if (_listRequest == null || !_listRequest.IsCompleted)
                {
                    return;
                }
                if (_listRequest.Status != StatusCode.Success)
                {
                    var message = _listRequest.Error == null
                        ? "Unity Package Manager list request failed."
                        : _listRequest.Error.message;
                    throw new InvalidOperationException(message);
                }
                if (EditorApplication.isCompiling || EditorApplication.isUpdating)
                {
                    _stableIdleTicksObserved = 0;
                    return;
                }

                _stableIdleTicksObserved++;
                if (_stableIdleTicksObserved < _stableIdleTicksRequired)
                {
                    return;
                }

                CompleteSuccess(
                    _listRequest.Result == null
                        ? Array.Empty<PackageInfo>()
                        : _listRequest.Result.ToArray());
            }
            catch (Exception ex)
            {
                CompleteFailure("package_restore_settle_failed", ex);
            }
        }

        static void CompleteSuccess(PackageInfo[] registeredPackages)
        {
            var projectRoot = Path.GetFullPath(XUUnityLightMcpFileIpcPaths.ProjectRootPath);
            var manifestPath = Path.Combine(projectRoot, "Packages", "manifest.json");
            var lockPath = Path.Combine(projectRoot, "Packages", "packages-lock.json");
            if (!File.Exists(manifestPath))
            {
                throw new FileNotFoundException("Packages/manifest.json is missing after package restore.", manifestPath);
            }
            if (!File.Exists(lockPath))
            {
                throw new FileNotFoundException("Packages/packages-lock.json is missing after package restore.", lockPath);
            }

            var directDependencies = registeredPackages
                .Where(item => item != null && item.isDirectDependency)
                .Select(item => item.name ?? "")
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .Distinct(StringComparer.Ordinal)
                .OrderBy(value => value, StringComparer.Ordinal)
                .ToArray();
            var missing = Array.Empty<string>();
            var packages = registeredPackages
                .Where(item => item != null)
                .OrderBy(item => item.name, StringComparer.Ordinal)
                .Select(item => new PackageRecord
                {
                    name = item.name ?? "",
                    version = item.version ?? "",
                    package_id = item.packageId ?? "",
                    source = item.source.ToString(),
                    direct_dependency = item.isDirectDependency
                })
                .ToArray();

            _result.request_status = "package_graph_registered";
            _result.stable_idle_ticks_observed = _stableIdleTicksObserved;
            _result.manifest_sha256 = Sha256(manifestPath);
            _result.packages_lock_sha256 = Sha256(lockPath);
            _result.packages = packages;
            _result.direct_dependencies = directDependencies;
            _result.missing_direct_dependencies = missing;
            _result.dependency_xml_sources = ReadDependencyXmlSources(projectRoot);
            _result.succeeded = packages.Length > 0 && missing.Length == 0;
            _result.decision_ready = _result.succeeded;
            _result.outcome = _result.succeeded ? "package_restore_completed" : "package_restore_failed";
            _result.top_actionable_error = _result.succeeded
                ? ""
                : "One or more direct manifest dependencies are absent from Unity's registered package graph.";
            FinalizeAndExit(_result.succeeded ? 0 : 1);
        }

        static void CompleteFailure(string status, Exception ex)
        {
            if (_result == null)
            {
                _result = new PackageRestoreResult();
            }
            _result.request_status = status;
            _result.succeeded = false;
            _result.decision_ready = false;
            _result.outcome = "package_restore_failed";
            _result.exception_message = ex == null ? "Package restore failed." : ex.Message;
            _result.top_actionable_error = _result.exception_message;
            Debug.LogException(ex);
            FinalizeAndExit(1);
        }

        static void FinalizeAndExit(int exitCode)
        {
            EditorApplication.update -= Tick;
            _result.completed_at_utc = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");
            _result.duration_seconds = Math.Round((DateTime.UtcNow - _startedAtUtc).TotalSeconds, 6);
            PersistResult(_resultFile, _result);
            if (Application.isBatchMode)
            {
                EditorApplication.Exit(exitCode);
            }
        }

        static DependencyXmlRecord[] ReadDependencyXmlSources(string projectRoot)
        {
            var files = new List<string>();
            foreach (var relativeRoot in new[] { "Assets", "Packages" })
            {
                var root = Path.Combine(projectRoot, relativeRoot);
                if (!Directory.Exists(root))
                {
                    continue;
                }
                files.AddRange(Directory.GetFiles(root, "*Dependencies.xml", SearchOption.AllDirectories));
            }
            return files
                .Distinct(StringComparer.Ordinal)
                .OrderBy(path => path, StringComparer.Ordinal)
                .Take(512)
                .Select(path => new DependencyXmlRecord
                {
                    path = ProjectRelativePath(projectRoot, path),
                    sha256 = Sha256(path),
                    size_bytes = new FileInfo(path).Length
                })
                .ToArray();
        }

        static string ProjectRelativePath(string projectRoot, string path)
        {
            var rootUri = new Uri(Path.GetFullPath(projectRoot).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar);
            var pathUri = new Uri(Path.GetFullPath(path));
            return Uri.UnescapeDataString(rootUri.MakeRelativeUri(pathUri).ToString()).Replace('\\', '/');
        }

        static string Sha256(string path)
        {
            using (var stream = File.OpenRead(path))
            using (var sha = SHA256.Create())
            {
                var bytes = sha.ComputeHash(stream);
                var builder = new StringBuilder(bytes.Length * 2);
                foreach (var value in bytes)
                {
                    builder.Append(value.ToString("x2"));
                }
                return builder.ToString();
            }
        }

        static int ParseStableIdleTicks(string raw)
        {
            if (!int.TryParse(raw, out var value))
            {
                return 2;
            }
            if (value < 2 || value > 10)
            {
                throw new InvalidOperationException($"{StableIdleTicksArg} must be between 2 and 10.");
            }
            return value;
        }

        static string ReadArg(string[] args, string name)
        {
            for (var i = 0; i < args.Length - 1; i++)
            {
                if (string.Equals(args[i], name, StringComparison.Ordinal))
                {
                    return args[i + 1] ?? "";
                }
            }
            return "";
        }

        static void PersistResult(string resultFile, PackageRestoreResult result)
        {
            if (string.IsNullOrWhiteSpace(resultFile))
            {
                return;
            }
            var fullPath = Path.GetFullPath(resultFile);
            var directory = Path.GetDirectoryName(fullPath);
            if (!string.IsNullOrWhiteSpace(directory))
            {
                Directory.CreateDirectory(directory);
            }
            XUUnityLightMcpAtomicFileWriter.WriteAllText(fullPath, JsonUtility.ToJson(result, true));
        }
    }
}
