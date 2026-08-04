using NUnit.Framework;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Operations;

namespace XUUnity.LightMcp.Tests.EditMode
{
    [Category("XUUnity.MCP.SelfTest")]
    [Category("XUUnity.MCP.EditMode")]
    [Category("XUUnity.MCP.Fast")]
    [Category("XUUnity.MCP.ArgumentContract")]
    public sealed class XUUnityLightMcpArgumentContractEditModeTests
    {
        [Test]
        public void AMissingCompileTargetIsNotReportedAsACompileFailure()
        {
            var response = Compile("{}");

            Assert.That(response.status, Is.EqualTo("error"));
            Assert.That(
                response.error.code,
                Is.EqualTo("operation_arguments_invalid"),
                "reporting compile_player_scripts_failed here read as a compile verdict for a compile that never ran");
            Assert.That(response.error.code, Is.Not.EqualTo("compile_player_scripts_failed"));
        }

        [Test]
        public void TheMissingTargetMessageNamesTheParameterAndItsValues()
        {
            var response = Compile("{}");

            Assert.That(response.error.message, Does.Contain("target"));
            Assert.That(response.error.message, Does.Contain("StandaloneOSX"));
            Assert.That(
                response.error.message,
                Does.Contain("Nothing was compiled"),
                "a caller must not have to guess whether the compile ran");
        }

        [Test]
        public void AnUnknownTargetIsAlsoAnArgumentProblem()
        {
            var response = Compile("{\"target\":\"NotARealBuildTarget\"}");

            Assert.That(response.status, Is.EqualTo("error"));
            Assert.That(response.error.code, Is.EqualTo("operation_arguments_invalid"));
            Assert.That(response.error.message, Does.Contain("NotARealBuildTarget"));
            Assert.That(response.error.message, Does.Contain("Nothing was compiled"));
        }

        [Test]
        public void ABlankTargetIsTreatedAsMissingRatherThanUnknown()
        {
            var response = Compile("{\"target\":\"   \"}");

            Assert.That(response.error.code, Is.EqualTo("operation_arguments_invalid"));
            Assert.That(response.error.message, Does.Contain("target is required"));
        }

        static XUUnityLightMcpResponse Compile(string argsJson)
        {
            return new XUUnityLightMcpCompilePlayerScriptsOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "argument-contract-selftest",
                operation = "unity.compile.player_scripts",
                args_json = argsJson
            });
        }
    }
}
