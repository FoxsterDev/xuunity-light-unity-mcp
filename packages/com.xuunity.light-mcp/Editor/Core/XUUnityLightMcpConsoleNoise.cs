using System.Text.RegularExpressions;

namespace XUUnity.LightMcp.Editor.Core
{
    /// <summary>
    /// Build-pipeline progress chatter that matches any feature keyword the compile job happens to be
    /// named after. Grep exists to answer "did this feature log a defect", and these lines can only
    /// ever bury that answer, so they are suppressed unless the caller explicitly asks for them.
    /// The host mirrors this pattern for the Editor.log lane; keep the two in step.
    /// </summary>
    internal static class XUUnityLightMcpConsoleNoise
    {
        public const string BuildPipelineProgressPattern =
            @"(^\s*(CopyFiles|CopyDirs|CopyFile|MoveFiles|WriteFile|Compile|Link|Strip)\s)|(^\s*\[\s*\d+\s*/\s*\d+\s)";

        static readonly Regex BuildPipelineProgress = new(
            BuildPipelineProgressPattern,
            RegexOptions.Compiled | RegexOptions.CultureInvariant);

        public static bool IsBuildPipelineProgress(string message)
        {
            return !string.IsNullOrEmpty(message) && BuildPipelineProgress.IsMatch(message);
        }
    }
}
