using System.Collections;
using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Operations;

namespace XUUnity.LightMcp.Tests.PlayModeUgui
{
    [Category("XUUnity.MCP.SelfTest")]
    [Category("XUUnity.MCP.PlayMode")]
    [Category("XUUnity.MCP.Fast")]
    [Category("XUUnity.MCP.UiRead")]
    [Category("XUUnity.MCP.SceneScope")]
    public sealed class XUUnityLightMcpUiSceneScopePlayModeTests
    {
        const string ADDITIVE_SCENE_NAME = "XUUnityMcp_AdditiveScope";

        readonly List<GameObject> _spawned = new();
        readonly List<Scene> _created = new();

        [SetUp]
        public void SetUp()
        {
            // This assembly has no platform restriction, so the EditMode runner also collects it. Edit Mode
            // refuses to add a scene while an untitled scene is unsaved -- the normal state of a working editor --
            // so multi-scene scope can only be proven at runtime, and the EditMode collection must skip rather
            // than fail.
            if (!Application.isPlaying)
            {
                Assert.Ignore("multi-scene scope is a runtime contract; run this through the PlayMode lane");
            }
        }

        [UnityTearDown]
        public IEnumerator UnityTearDown()
        {
            foreach (var spawned in _spawned)
            {
                if (spawned != null)
                {
                    Object.DestroyImmediate(spawned);
                }
            }

            _spawned.Clear();

            foreach (var scene in _created)
            {
                if (scene.IsValid() && scene.isLoaded)
                {
                    yield return SceneManager.UnloadSceneAsync(scene);
                }
            }

            _created.Clear();
        }

        [Test]
        public void ActiveScene_CannotSeeAnAdditiveScene_AndSaysSoAsOutOfScope()
        {
            BuildCanvasInAdditiveScene("Card");

            var payload = RunQuery(
                "{\"targetKind\":\"active_scene\",\"includeDontDestroyOnLoad\":false,"
                + "\"includeInactive\":true,\"selector\":{\"name\":\"Card\"}}");

            Assert.That(payload.match_count, Is.EqualTo(0), "the additive scene must be outside active_scene");
            Assert.That(payload.out_of_scope, Is.True, "a reachable-but-unsearched target is not 'not found'");
            Assert.That(
                payload.warnings.Exists(item => item.code == "ui_target_out_of_scope"),
                Is.True,
                "the zero-match answer must carry the scope diagnostic");
            Assert.That(payload.target.loaded_scenes.Count, Is.GreaterThan(payload.target.searched_scenes.Count));
        }

        [Test]
        public void AllLoadedScenes_FindsTheNodeAndTagsItWithItsOwningScene()
        {
            BuildCanvasInAdditiveScene("Card");

            var payload = RunQuery(
                "{\"targetKind\":\"all_loaded_scenes\",\"includeInactive\":true,\"maxNodes\":2000,"
                + "\"selector\":{\"name\":\"Card\"}}");

            Assert.That(payload.success, Is.True);
            Assert.That(payload.match_count, Is.EqualTo(1));
            Assert.That(payload.out_of_scope, Is.False);
            Assert.That(payload.matches[0].scene_name, Is.EqualTo(ADDITIVE_SCENE_NAME));
            Assert.That(payload.target.searched_scenes, Contains.Item(ADDITIVE_SCENE_NAME));
        }

        [Test]
        public void OutOfScopeOnRootResolution_AlsoSetsTheFirstClassBoolean()
        {
            BuildCanvasInAdditiveScene("Card");

            var payload = RunQuery(
                "{\"targetKind\":\"game_object_name\",\"targetValue\":\"XUUnityMcp_ScopeCanvas\","
                + "\"includeDontDestroyOnLoad\":false,\"includeInactive\":true,\"selector\":{\"name\":\"Card\"}}");

            Assert.That(payload.success, Is.False);
            Assert.That(
                payload.errors.Exists(item => item.code == "ui_target_out_of_scope"),
                Is.True,
                "the root lives in an unsearched scene");
            Assert.That(
                payload.out_of_scope,
                Is.True,
                "out_of_scope was only assigned on the zero-match path, so the error path left it false");

            var diagnostic = payload.errors.Find(item => item.code == "ui_target_out_of_scope");
            Assert.That(
                diagnostic.detail,
                Does.Contain("sceneName"),
                "targetKind is the root selector for the name kind, so sceneName is the only retry that keeps it");
        }

        [Test]
        public void AMissingSceneNameNeverNamesAnUnsearchedSceneAsTheTarget()
        {
            BuildCanvasInAdditiveScene("Card");

            var payload = RunTree("{\"targetKind\":\"all_loaded_scenes\",\"sceneName\":\"XUUnityMcp_NoSuchScene\"}");

            Assert.That(payload.success, Is.False);
            Assert.That(payload.errors[0].code, Is.EqualTo("ui_target_out_of_scope"));
            Assert.That(payload.target.searched_scenes, Is.Empty);
            Assert.That(
                payload.target.scene_name,
                Is.Empty,
                "reporting the active scene here claimed a scope the call never searched");
        }

        [Test]
        public void ASceneNameMatchingSeveralLoadedScenesIsNamedRatherThanSilentlyWidened()
        {
            BuildCanvasInAdditiveScene("Card");

            Scene twin;
            try
            {
                twin = NewAdditiveScene(ADDITIVE_SCENE_NAME);
            }
            catch (System.ArgumentException)
            {
                // SceneManager.CreateScene refuses a duplicate name, so this shape needs two scene *assets* that
                // share a file name in different folders, or the same scene asset loaded twice additively. Neither
                // is worth writing into a consumer project from a self-test.
                Assert.Ignore("runtime scene creation refuses duplicate names; this needs saved scene assets");
                return;
            }

            if (twin.name != ADDITIVE_SCENE_NAME)
            {
                Assert.Ignore("this editor renames a second scene created with the same name");
            }

            var payload = RunTree($"{{\"sceneName\":\"{ADDITIVE_SCENE_NAME}\"}}");

            Assert.That(payload.target.scene_selector_ambiguous, Is.True);
            Assert.That(payload.warnings.Exists(item => item.code == "ui_scene_selector_ambiguous"), Is.True);
        }

        [Test]
        public void ATruncatedWiderScopeProbeDoesNotClaimTheNodeIsNowhere()
        {
            BuildCanvasInAdditiveScene("Card");

            var payload = RunQuery(
                "{\"targetKind\":\"active_scene\",\"includeDontDestroyOnLoad\":false,\"includeInactive\":true,"
                + "\"maxNodes\":1,\"selector\":{\"name\":\"XUUnityMcp_NoSuchNode\"}}");

            Assert.That(payload.match_count, Is.EqualTo(0));
            Assert.That(
                payload.warnings.Exists(item => item.code == "ui_scope_probe_incomplete")
                || payload.errors.Exists(item => item.code == "ui_scope_probe_incomplete"),
                Is.True,
                "a probe stopped by the node budget cannot support 'no node in any loaded scene'");
        }

        [Test]
        [Category("XUUnity.MCP.KnownGap")]
        public void ANodeBudgetSpentOnAnEarlierSceneSilentlySkipsLaterScenes()
        {
            BuildCanvasInAdditiveScene("Card");

            var payload = RunTree(
                "{\"targetKind\":\"all_loaded_scenes\",\"includeInactive\":true,\"maxNodes\":1}");

            Assert.That(payload.truncated, Is.True, "the budget is exhausted before the last scene is reached");
            Assert.That(
                payload.target.searched_scenes.Count,
                Is.GreaterThan(1),
                "searched_scenes still lists every scene in scope");

            var reachedScenes = new List<string>();
            foreach (var node in payload.nodes)
            {
                if (!reachedScenes.Contains(node.scene_name))
                {
                    reachedScenes.Add(node.scene_name);
                }
            }

            Assert.That(
                reachedScenes.Count,
                Is.EqualTo(payload.target.searched_scenes.Count),
                "KNOWN GAP: roots are walked under one shared node budget in scope order and the walk breaks on "
                + "the first truncation, so later scenes are never reached while searched_scenes claims they "
                + "were. DontDestroyOnLoad is appended last, so it is the first scope to disappear on a real "
                + "tree. Fixing it needs a contract decision: per-scene budgets, or a scenes_not_reached field.");
        }

        void BuildCanvasInAdditiveScene(string childName)
        {
            var scene = NewAdditiveScene(ADDITIVE_SCENE_NAME);

            var canvasRoot = new GameObject("XUUnityMcp_ScopeCanvas", typeof(RectTransform), typeof(Canvas));
            SceneManager.MoveGameObjectToScene(canvasRoot, scene);
            _spawned.Add(canvasRoot);

            canvasRoot.GetComponent<Canvas>().renderMode = RenderMode.ScreenSpaceOverlay;
            canvasRoot.GetComponent<RectTransform>().sizeDelta = new Vector2(1080f, 1920f);

            var child = new GameObject(childName, typeof(RectTransform));
            child.transform.SetParent(canvasRoot.transform, false);
            child.GetComponent<RectTransform>().sizeDelta = new Vector2(600f, 400f);
        }

        Scene NewAdditiveScene(string sceneName)
        {
            var scene = SceneManager.CreateScene(sceneName);
            if (!scene.IsValid() || !scene.isLoaded)
            {
                Assert.Ignore($"this runtime did not create an additive scene named {sceneName}");
            }

            _created.Add(scene);
            return scene;
        }

        static XUUnityLightMcpUiTreePayload RunTree(string argsJson)
        {
            var response = new XUUnityLightMcpUiTreeSnapshotOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "ui-scene-scope-playmode",
                operation = "unity.ui.tree_snapshot",
                args_json = argsJson
            });
            Assert.That(response.status, Is.EqualTo("ok"));
            return JsonUtility.FromJson<XUUnityLightMcpUiTreePayload>(response.payload_json);
        }

        static XUUnityLightMcpUiQueryPayload RunQuery(string argsJson)
        {
            var response = new XUUnityLightMcpUiQueryOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "ui-scene-scope-playmode-query",
                operation = "unity.ui.query",
                args_json = argsJson
            });
            Assert.That(response.status, Is.EqualTo("ok"));
            return JsonUtility.FromJson<XUUnityLightMcpUiQueryPayload>(response.payload_json);
        }
    }
}
