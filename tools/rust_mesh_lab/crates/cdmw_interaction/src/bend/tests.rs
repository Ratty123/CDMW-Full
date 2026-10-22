use super::*;
use crate::OperatorController;
use cdmw_formats::{MeshFormat, decode_mesh};
use cdmw_mesh::{History, Selection};

fn rope() -> (WorkingMesh, Vec<Vec<VertexHandle>>, Vec<VertexHandle>) {
    let mut doc = decode_mesh(
        &cdmw_formats::synthetic::triangle_pam("owned.dds"),
        MeshFormat::Pam,
    )
    .unwrap();
    let part = &mut doc.lods[0].submeshes[0];
    part.positions.clear();
    part.indices.clear();
    for ring in -2..=10 {
        for side in 0..8 {
            let angle = side as f32 * std::f32::consts::TAU / 8.0;
            part.positions
                .push([ring as f32, 0.15 * angle.cos(), 0.15 * angle.sin()]);
        }
    }
    for ring in 0..12 {
        for side in 0..8 {
            let a = ring * 8 + side;
            let b = ring * 8 + (side + 1) % 8;
            part.indices.extend([a, b, b + 8, a, b + 8, a + 8]);
        }
    }
    // A nearby disconnected island in the same Part must remain exact.
    part.positions
        .extend([[4.0, 0.16, 0.2], [4.1, 0.16, 0.2], [4.0, 0.26, 0.2]]);
    part.indices.extend([104, 105, 106]);
    part.normals = vec![[0.0, 0.0, 1.0]; part.positions.len()];
    part.uvs = vec![[0.25, 0.75]; part.positions.len()];
    part.source_vertex_indices = (0..part.positions.len() as i32).collect();
    // Even perfectly coincident geometry in another selected Part is excluded.
    let other = part.clone();
    doc.lods[0].submeshes.push(other);
    let mut mesh = WorkingMesh::from_document(&doc).unwrap();
    let mut rings = vec![Vec::new(); 13];
    let mut outside = Vec::new();
    for (handle, vertex) in mesh.vertices() {
        match vertex.provenance {
            Provenance::Source {
                submesh: 0,
                element,
            } if element < 104 => rings[element as usize / 8].push(handle),
            _ => outside.push(handle),
        }
    }
    mesh.set_selection(Selection {
        vertices: mesh.vertices().map(|(handle, _)| handle).collect(),
        ..Selection::default()
    })
    .unwrap();
    (mesh, rings, outside)
}

#[test]
fn bend_preserves_thickness_fixed_side_nearby_parts_and_one_entry_history() {
    let (mut mesh, rings, outside) = rope();
    let before = mesh.clone();
    let region = BendRegion::new(&mesh, rings[2][0]).unwrap();
    assert_eq!(104, region.handles.len());
    let stroke = BendStroke::new(&mesh, &region, rings[10][0]).unwrap();
    let mut operator = OperatorController::default();
    let mut history = History::new(16 * 1024 * 1024);
    let id = operator.begin(&mesh, "Bend").unwrap();
    for step in 1..=20 {
        operator
            .bend(&mut mesh, id, &stroke, Vec3::Y * (step as f32 / 5.0))
            .unwrap();
    }
    for handle in rings[..=2].iter().flatten() {
        assert_eq!(
            before.vertex(*handle).unwrap().position,
            mesh.vertex(*handle).unwrap().position
        );
    }
    for handle in &outside {
        assert_eq!(before.vertex(*handle), mesh.vertex(*handle));
    }
    let mut centers = Vec::new();
    for ring in &rings[2..=10] {
        let center = ring
            .iter()
            .map(|h| Vec3::from_array(mesh.vertex(*h).unwrap().position))
            .sum::<Vec3>()
            / 8.0;
        for handle in ring {
            let radius = Vec3::from_array(mesh.vertex(*handle).unwrap().position).distance(center);
            assert!((radius - 0.15).abs() < 2.0e-5, "radius {radius}");
        }
        centers.push(center);
    }
    let measured_length: f32 = centers
        .windows(2)
        .map(|pair| pair[0].distance(pair[1]))
        .sum();
    assert!((measured_length - 8.0).abs() < 0.01);
    let changed = mesh.clone();
    operator.confirm(&mut mesh, &mut history, id).unwrap();
    assert_eq!(1, history.undo_len());
    history.undo(&mut mesh).unwrap();
    assert!(
        before
            .vertices()
            .all(|(handle, vertex)| mesh.vertex(handle) == Some(vertex))
    );
    history.redo(&mut mesh).unwrap();
    assert!(
        changed
            .vertices()
            .all(|(handle, vertex)| mesh.vertex(handle) == Some(vertex))
    );
    assert_eq!(before.faces().count(), mesh.faces().count());
    mesh.validate().unwrap();
}

#[test]
fn bend_samples_do_not_accumulate_stretch_and_cancel_keeps_the_redo_branch() {
    let (mut mesh, rings, _) = rope();
    let before = mesh.clone();
    let region = BendRegion::new(&mesh, rings[2][0]).unwrap();
    let stroke = BendStroke::new(&mesh, &region, rings[10][0]).unwrap();
    let mut operator = OperatorController::default();
    let mut history = History::new(16 * 1024 * 1024);
    let id = operator.begin(&mesh, "Bend").unwrap();
    operator
        .bend(&mut mesh, id, &stroke, Vec3::Z * 4.0)
        .unwrap();
    operator.confirm(&mut mesh, &mut history, id).unwrap();
    history.undo(&mut mesh).unwrap();
    let id = operator.begin(&mesh, "Bend").unwrap();
    for delta in [1.0, 4.0, -2.0, 4.0] {
        operator
            .bend(&mut mesh, id, &stroke, Vec3::Z * delta)
            .unwrap();
    }
    let once = stroke.positions(Vec3::Z * 4.0).unwrap();
    for (handle, position) in once {
        assert_eq!(position, mesh.vertex(handle).unwrap().position);
    }
    operator.cancel(&mut mesh, id).unwrap();
    assert!(
        before
            .vertices()
            .all(|(handle, vertex)| mesh.vertex(handle) == Some(vertex))
    );
    history.redo(&mut mesh).unwrap();
    assert_ne!(
        before.structural_fingerprint(),
        mesh.structural_fingerprint()
    );
}

#[test]
fn bend_refuses_missing_selection_stale_regions_and_unselected_tips() {
    let (mut mesh, rings, outside) = rope();
    let region = BendRegion::new(&mesh, rings[2][0]).unwrap();
    assert!(BendStroke::new(&mesh, &region, outside[0]).is_err());
    assert!(BendStroke::new(&mesh, &region, rings[2][0]).is_err());
    mesh.set_selection(Selection::default()).unwrap();
    assert!(!region.matches(&mesh));
    assert!(BendRegion::new(&mesh, rings[2][0]).is_err());
    assert!(BendStroke::new(&mesh, &region, rings[10][0]).is_err());
}

#[test]
fn bend_connects_exact_selected_seams_without_crossing_a_part_boundary() {
    let mut doc = decode_mesh(
        &cdmw_formats::synthetic::triangle_pam("owned.dds"),
        MeshFormat::Pam,
    )
    .unwrap();
    let part = &mut doc.lods[0].submeshes[0];
    part.positions = vec![
        [0., 0., 0.],
        [1., 0., 0.],
        [0., 1., 0.],
        [1., 0., 0.],
        [1., 1., 0.],
        [0., 1., 0.],
    ];
    part.indices = vec![0, 1, 2, 3, 4, 5];
    part.normals = vec![[0., 0., 1.]; 6];
    part.uvs = vec![[0., 0.]; 6];
    part.source_vertex_indices = (0..6).collect();
    let mut mesh = WorkingMesh::from_document(&doc).unwrap();
    let handles = mesh
        .vertices()
        .map(|(handle, _)| handle)
        .collect::<Vec<_>>();
    mesh.set_selection(Selection {
        vertices: handles.iter().copied().collect(),
        ..Selection::default()
    })
    .unwrap();
    let region = BendRegion::new(&mesh, handles[0]).unwrap();
    assert_eq!(6, region.handles.len());
    mesh.set_selection(Selection {
        vertices: handles[..3].iter().copied().collect(),
        ..Selection::default()
    })
    .unwrap();
    assert_eq!(3, BendRegion::new(&mesh, handles[0]).unwrap().handles.len());
}

#[test]
fn bend_refuses_a_stroke_from_another_mesh_and_preserves_generated_connections() {
    let (mesh, rings, _) = rope();
    let region = BendRegion::new(&mesh, rings[2][0]).unwrap();
    let stroke = BendStroke::new(&mesh, &region, rings[10][0]).unwrap();
    let (mut other, other_rings, _) = rope();
    let before = other.structural_fingerprint();
    let mut operator = OperatorController::default();
    let id = operator.begin(&other, "Bend").unwrap();
    assert!(operator.bend(&mut other, id, &stroke, Vec3::Y).is_err());
    assert_eq!(before, other.structural_fingerprint());
    operator.cancel(&mut other, id).unwrap();
    let faces = other
        .faces()
        .filter_map(|(handle, face)| (face.submesh == 0).then_some(handle))
        .collect();
    other.subdivide_faces(&faces).unwrap();
    let generated = other
        .vertices()
        .filter(|(_, vertex)| matches!(vertex.provenance, Provenance::Generated { .. }))
        .count();
    assert!(generated > 0);
    let region = BendRegion::new(&other, other_rings[2][0]).unwrap();
    assert!(
        region.handles.len() > 104,
        "subdivided rope stays connected across generated vertices"
    );
}
