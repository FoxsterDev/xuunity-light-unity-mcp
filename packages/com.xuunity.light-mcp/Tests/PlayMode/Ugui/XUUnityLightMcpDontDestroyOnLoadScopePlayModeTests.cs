using NUnit.Framework;
using UnityEngine;
using UnityEngine.UI;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Operations;

namespace XUUnity.LightMcp.Tests.PlayModeUgui
{
    [Category("XUUnity.MCP.SelfTest")]
    [Category("XUUnity.MCP.PlayMode")]
    [Category("XUUnity.MCP.Fast")]
    [Category("XUUnity.MCP.UiRead")]
    [Category("XUUnity.MCP.SceneScope")]
    public sealed class XUUnityLightMcpDontDestroyOnLoadScopePlayModeTests
    {
        const string PROBE_NAME = "XUUnityLightMcpDontDestroyOnLoadProbe";

        GameObject _overlayRoot;

        [SetUp]
        public void SetUp()
        {
            if (!Application.isPlaying)
            {
                Assert.Ignore("DontDestroyOnLoad only exists at runtime; run this through the PlayMode lane");
            }

            _overlayRoot = new GameObject("XUUnityMcp_DdolOverlay", typeof(RectTransform), typeof(Canvas));
            _overlayRoot.GetComponent<Canvas>().renderMode = RenderMode.ScreenSpaceOverlay;
            _overlayRoot.GetComponent<RectTransform>().sizeDelta = new Vector2(1080f, 1920f);

            var badge = new GameObject("DdolBadge", typeof(RectTransform), typeof(Image));
            badge.transform.SetParent(_overlayRoot.transform, false);
            badge.GetComponent<RectTransform>().sizeDelta = new Vector2(240f, 240f);

            Object.DontDestroyOnLoad(_overlayRoot);
        }

        [TearDown]
        public void TearDown()
        {
            if (_overlayRoot != null)
            {
                Object.DestroyImmediate(_overlayRoot);
                _overlayRoot = null;
            }
        }

        [Test]
        public void AllLoadedScenes_ReachesDontDestroyOnLoadAndReportsItAsIncluded()
        {
            var payload = RunQuery(
                "{\"targetKind\":\"all_loaded_scenes\",\"includeDontDestroyOnLoad\":true,"
                + "\"includeInactive\":true,\"maxNodes\":2000,\"selector\":{\"name\":\"DdolBadge\"}}");

            Assert.That(payload.success, Is.True);
            Assert.That(payload.match_count, Is.EqualTo(1), "the overlay must be reachable at the widest scope");
            Assert.That(payload.matches[0].scene_name, Is.EqualTo("DontDestroyOnLoad"));
            Assert.That(payload.target.dont_destroy_on_load_included, Is.True);
            Assert.That(payload.target.dont_destroy_on_load_status, Is.EqualTo("included"));
            Assert.That(payload.target.searched_scenes, Contains.Item("DontDestroyOnLoad"));
        }

        [Test]
        public void ActiveScene_ReportsDontDestroyOnLoadAsOutOfScopeRatherThanIncluded()
        {
            var payload = RunQuery(
                "{\"targetKind\":\"active_scene\",\"includeDontDestroyOnLoad\":true,"
                + "\"includeInactive\":true,\"selector\":{\"name\":\"DdolBadge\"}}");

            Assert.That(payload.target.dont_destroy_on_load_included, Is.False);
            Assert.That(
                payload.target.dont_destroy_on_load_status,
                Is.EqualTo("out_of_scope_for_target_kind"),
                "reporting 'included' while the flag was false read as a contradiction on a live run");
            Assert.That(payload.out_of_scope, Is.True, "the badge exists, it is merely unreachable at this scope");
        }

        [Test]
        public void OptingOutOfDontDestroyOnLoadIsReportedAsNotRequested()
        {
            var payload = RunQuery(
                "{\"targetKind\":\"all_loaded_scenes\",\"includeDontDestroyOnLoad\":false,"
                + "\"includeInactive\":true,\"selector\":{\"name\":\"DdolBadge\"}}");

            Assert.That(payload.target.dont_destroy_on_load_included, Is.False);
            Assert.That(payload.target.dont_destroy_on_load_status, Is.EqualTo("not_requested"));
            Assert.That(payload.target.searched_scenes, Does.Not.Contain("DontDestroyOnLoad"));
        }

        [Test]
        public void TheHiddenProbeNeverSurvivesTheCallThatCreatedIt()
        {
            for (var attempt = 0; attempt < 3; attempt++)
            {
                RunQuery(
                    "{\"targetKind\":\"all_loaded_scenes\",\"includeDontDestroyOnLoad\":true,"
                    + "\"includeInactive\":true,\"maxNodes\":2000,\"selector\":{\"name\":\"DdolBadge\"}}");
            }

            var leaked = 0;
            foreach (var transform in Object.FindObjectsByType<Transform>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (transform.name == PROBE_NAME)
                {
                    leaked++;
                }
            }

            Assert.That(leaked, Is.EqualTo(0), "the DontDestroyOnLoad probe must be destroyed in its finally block");

            var selfMatch = RunQuery(
                "{\"targetKind\":\"all_loaded_scenes\",\"includeDontDestroyOnLoad\":true,"
                + "\"includeInactive\":true,\"maxNodes\":2000,\"selector\":{\"name\":\"" + PROBE_NAME + "\"}}");

            Assert.That(
                selfMatch.match_count,
                Is.EqualTo(0),
                "the probe must not appear in the node set of the very call that creates it");
        }

        static XUUnityLightMcpUiQueryPayload RunQuery(string argsJson)
        {
            var response = new XUUnityLightMcpUiQueryOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "ddol-scope-regression",
                operation = "unity.ui.query",
                args_json = argsJson
            });
            Assert.That(response.status, Is.EqualTo("ok"));
            return JsonUtility.FromJson<XUUnityLightMcpUiQueryPayload>(response.payload_json);
        }
    }
}
