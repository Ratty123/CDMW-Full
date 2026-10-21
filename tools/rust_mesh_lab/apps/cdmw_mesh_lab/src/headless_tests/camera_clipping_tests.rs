use super::*;

#[test]
fn edited_mesh_depth_stays_inside_camera_clip_planes_without_reframing() -> TestResult {
    for host_update in [true, false] {
        let mut application = triangle_application()?;
        application.camera.zoom(-1500.0);
        let navigation = application.camera.orbit_state();
        let fit_target = application.camera.fit_target();
        let relative_zoom = application.camera.relative_zoom();
        let camera_revision = application.camera.revision();

        if host_update {
            let mut replacement = application.document.as_deref().cloned().ok_or("document")?;
            for position in &mut replacement.lods[0].submeshes[0].positions {
                position[2] += 30.0;
            }
            application.install_cdmw_document(replacement)?;
        } else {
            let mesh = application.mesh.as_mut().ok_or("working mesh")?;
            let handles = mesh.vertices().map(|(handle, _)| handle).collect();
            mesh.translate_vertices(&handles, Vec3::Z * 30.0)?;
            application.publish_mesh_snapshot();
        }

        assert_eq!(application.camera.orbit_state(), navigation);
        assert_eq!(application.camera.fit_target(), fit_target);
        assert_eq!(application.camera.relative_zoom(), relative_zoom);
        assert!(application.camera.revision() > camera_revision);

        for yaw in [0.0, std::f32::consts::FRAC_PI_2, std::f32::consts::PI] {
            application
                .camera
                .set_orbit_state_with_roll(yaw, 0.0, 0.0, None, None);
            let mesh = application.mesh.as_ref().ok_or("updated mesh")?;
            for (_, vertex) in mesh.vertices() {
                let position = Vec3::from_array(vertex.position);
                let projected = application
                    .camera
                    .project(position, viewport())
                    .ok_or("projection")?;
                assert!(
                    (0.0..=1.0).contains(&projected.depth),
                    "host_update={host_update}, yaw={yaw}: edited point {position:?} was clipped at depth {}",
                    projected.depth,
                );
                let (origin, direction, maximum) = application
                    .camera
                    .screen_ray(projected.screen, viewport())
                    .ok_or("picking ray")?;
                let distance = (position - origin).dot(direction);
                assert!(
                    distance >= 0.0 && distance <= maximum,
                    "edited point fell beyond picking depth"
                );
            }
        }
    }
    Ok(())
}
