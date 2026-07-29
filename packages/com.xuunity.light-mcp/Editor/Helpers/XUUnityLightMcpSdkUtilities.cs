using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using XUUnity.LightMcp.Editor.Core;

namespace XUUnity.LightMcp.Editor.Helpers
{
    internal static class XUUnityLightMcpSdkPaths
    {
        public static bool TryResolveProjectFile(string path, out string fullPath, out string error)
        {
            fullPath = "";
            error = "";

            try
            {
                var projectRoot = Path.GetFullPath(XUUnityLightMcpFileIpcPaths.ProjectRootPath);
                fullPath = Path.IsPathRooted(path)
                    ? Path.GetFullPath(path)
                    : Path.GetFullPath(Path.Combine(projectRoot, path));

                var rootWithSeparator = projectRoot.EndsWith(Path.DirectorySeparatorChar.ToString(), StringComparison.Ordinal)
                    ? projectRoot
                    : projectRoot + Path.DirectorySeparatorChar;

                if (!string.Equals(fullPath, projectRoot, StringComparison.Ordinal)
                    && !fullPath.StartsWith(rootWithSeparator, StringComparison.Ordinal))
                {
                    error = "Path must resolve inside the Unity project root.";
                    return false;
                }

                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }
    }

    internal static class XUUnityLightMcpSdkHash
    {
        public static string ComputeSha256(string path)
        {
            using var sha = SHA256.Create();
            using var stream = File.OpenRead(path);
            var hash = sha.ComputeHash(stream);
            var builder = new StringBuilder(hash.Length * 2);
            foreach (var b in hash)
            {
                builder.Append(b.ToString("x2"));
            }

            return builder.ToString();
        }
    }

    internal static class XUUnityLightMcpEdm4uAdapter
    {
        const string ResolverTypeName = "GooglePlayServices.PlayServicesResolver";

        public static bool TryDescribe(out string adapter, out string reason)
        {
            if (TryResolveMethod(out var method))
            {
                adapter = $"{method.DeclaringType?.FullName}.Resolve(Action,bool,Action<bool>)";
                reason = "";
                return true;
            }

            adapter = "";
            reason =
                "External Dependency Manager for Unity with the callback-capable " +
                "GooglePlayServices.PlayServicesResolver.Resolve API is not loaded.";
            return false;
        }

        public static bool TryStart(bool force, Action<bool> completion, out string adapter, out string error)
        {
            adapter = "";
            error = "";
            if (!TryResolveMethod(out var method))
            {
                error =
                    "External Dependency Manager for Unity does not expose the required " +
                    "PlayServicesResolver.Resolve(Action,bool,Action<bool>) callback API.";
                return false;
            }

            adapter = $"{method.DeclaringType?.FullName}.Resolve(Action,bool,Action<bool>)";
            try
            {
                method.Invoke(null, new object[] { null, force, completion });
                return true;
            }
            catch (TargetInvocationException ex)
            {
                error = ex.InnerException?.Message ?? ex.Message;
                return false;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }

        static bool TryResolveMethod(out MethodInfo method)
        {
            method = null;
            var resolverType = AppDomain.CurrentDomain
                .GetAssemblies()
                .Select(assembly => assembly.GetType(ResolverTypeName, false))
                .FirstOrDefault(type => type != null);
            if (resolverType == null)
            {
                return false;
            }

            method = resolverType
                .GetMethods(BindingFlags.Public | BindingFlags.Static)
                .FirstOrDefault(candidate =>
                {
                    if (!string.Equals(candidate.Name, "Resolve", StringComparison.Ordinal))
                    {
                        return false;
                    }

                    var parameters = candidate.GetParameters();
                    return parameters.Length == 3
                           && parameters[0].ParameterType == typeof(Action)
                           && parameters[1].ParameterType == typeof(bool)
                           && parameters[2].ParameterType == typeof(Action<bool>);
                });
            return method != null;
        }
    }
}
