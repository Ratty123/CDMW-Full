DirectX::XMFLOAT3 Renderer::add3(const DirectX::XMFLOAT3& a, const DirectX::XMFLOAT3& b) {
        return DirectX::XMFLOAT3(a.x + b.x, a.y + b.y, a.z + b.z);
    }

DirectX::XMFLOAT3 Renderer::sub3(const DirectX::XMFLOAT3& a, const DirectX::XMFLOAT3& b) {
        return DirectX::XMFLOAT3(a.x - b.x, a.y - b.y, a.z - b.z);
    }

DirectX::XMFLOAT3 Renderer::mul3(const DirectX::XMFLOAT3& a, float scale) {
        return DirectX::XMFLOAT3(a.x * scale, a.y * scale, a.z * scale);
    }

float Renderer::dot3(const DirectX::XMFLOAT3& a, const DirectX::XMFLOAT3& b) {
        return a.x * b.x + a.y * b.y + a.z * b.z;
    }

float Renderer::length3(const DirectX::XMFLOAT3& value) {
        return std::sqrt(std::max(0.0f, dot3(value, value)));
    }

DirectX::XMFLOAT3 Renderer::normalize3(
        const DirectX::XMFLOAT3& value,
        const DirectX::XMFLOAT3& fallback) {
        float length = length3(value);
        if (length <= 1e-8f || !std::isfinite(length)) return fallback;
        return mul3(value, 1.0f / length);
    }

bool Renderer::load_cloth_runtime(PreviewBatch& batch, RendererStats& stats) {
        ClothRuntime& cloth = batch.cloth;
        cloth.initialized = false;
        if (!cloth.available) return false;
        std::vector<uint8_t> particle_data = read_binary(cloth.particle_file);
        std::vector<uint8_t> pin_data = read_binary(cloth.pin_file);
        std::vector<uint8_t> constraint_data = read_binary(cloth.constraint_file);
        const size_t particle_count = static_cast<size_t>(std::max(0, cloth.particle_count));
        if (particle_count == 0 || particle_data.size() < particle_count * sizeof(float) * 3u) {
            stats.skipped.push_back("cloth particles missing/truncated:" + std::to_string(batch.index));
            cloth.available = false;
            return false;
        }
        cloth.rest_positions.clear();
        cloth.positions.clear();
        cloth.previous_positions.clear();
        cloth.pin_weights.clear();
        cloth.constraints.clear();
        cloth.rest_positions.reserve(particle_count);
        const float* particles = reinterpret_cast<const float*>(particle_data.data());
        for (size_t index = 0; index < particle_count; ++index) {
            DirectX::XMFLOAT3 position(particles[index * 3u], particles[index * 3u + 1u], particles[index * 3u + 2u]);
            cloth.rest_positions.push_back(position);
            cloth.positions.push_back(position);
            cloth.previous_positions.push_back(position);
        }
        if (pin_data.size() >= particle_count * sizeof(float)) {
            const float* pins = reinterpret_cast<const float*>(pin_data.data());
            for (size_t index = 0; index < particle_count; ++index) {
                cloth.pin_weights.push_back(std::clamp(pins[index], 0.0f, 1.0f));
            }
        } else {
            cloth.pin_weights.assign(particle_count, 0.0f);
        }
        constexpr size_t kConstraintBytes = sizeof(int32_t) * 2u + sizeof(float) * 2u;
        const size_t constraint_count = constraint_data.size() / kConstraintBytes;
        cloth.constraints.reserve(constraint_count);
        for (size_t index = 0; index < constraint_count; ++index) {
            const uint8_t* ptr = constraint_data.data() + index * kConstraintBytes;
            const int32_t* ints = reinterpret_cast<const int32_t*>(ptr);
            const float* floats = reinterpret_cast<const float*>(ptr + sizeof(int32_t) * 2u);
            ClothConstraint constraint;
            constraint.a = static_cast<int>(ints[0]);
            constraint.b = static_cast<int>(ints[1]);
            constraint.rest_length = std::max(0.0f, floats[0]);
            constraint.stiffness = std::clamp(floats[1], 0.0f, 1.0f);
            if (
                constraint.a >= 0
                && constraint.b >= 0
                && static_cast<size_t>(constraint.a) < particle_count
                && static_cast<size_t>(constraint.b) < particle_count
                && constraint.a != constraint.b
            ) {
                cloth.constraints.push_back(constraint);
            }
        }
        cloth.constraint_count = static_cast<int>(cloth.constraints.size());
        cloth.initialized = true;
        return true;
    }

bool Renderer::cloth_preview_active() const {
        if (!cloth_state_.enabled || cloth_state_.paused) return false;
        for (const PreviewBatch& batch : batches_) {
            if (batch.cloth.initialized) return true;
        }
        return false;
    }

void Renderer::collide_point_with_sphere(DirectX::XMFLOAT3& point, const DirectX::XMFLOAT3& center, float radius) {
        if (radius <= 0.0f) return;
        DirectX::XMFLOAT3 delta = sub3(point, center);
        float length = length3(delta);
        if (length >= radius || length <= 1e-8f) return;
        DirectX::XMFLOAT3 normal = length > 1e-8f ? mul3(delta, 1.0f / length) : DirectX::XMFLOAT3(0.0f, 1.0f, 0.0f);
        point = add3(center, mul3(normal, radius + 0.004f));
    }

void Renderer::collide_point_with_capsule(DirectX::XMFLOAT3& point, const ClothCollider& collider) {
        DirectX::XMFLOAT3 segment = sub3(collider.b, collider.a);
        float denom = dot3(segment, segment);
        float t = denom > 1e-8f ? std::clamp(dot3(sub3(point, collider.a), segment) / denom, 0.0f, 1.0f) : 0.0f;
        collide_point_with_sphere(point, add3(collider.a, mul3(segment, t)), collider.radius);
    }

void Renderer::collide_point_with_aabb(DirectX::XMFLOAT3& point, const ClothCollider& collider) {
        if (
            point.x < collider.a.x || point.x > collider.b.x
            || point.y < collider.a.y || point.y > collider.b.y
            || point.z < collider.a.z || point.z > collider.b.z
        ) {
            return;
        }
        float distances[6] = {
            point.x - collider.a.x,
            collider.b.x - point.x,
            point.y - collider.a.y,
            collider.b.y - point.y,
            point.z - collider.a.z,
            collider.b.z - point.z,
        };
        int best = 0;
        for (int index = 1; index < 6; ++index) {
            if (distances[index] < distances[best]) best = index;
        }
        constexpr float kMargin = 0.006f;
        if (best == 0) point.x = collider.a.x - kMargin;
        else if (best == 1) point.x = collider.b.x + kMargin;
        else if (best == 2) point.y = collider.a.y - kMargin;
        else if (best == 3) point.y = collider.b.y + kMargin;
        else if (best == 4) point.z = collider.a.z - kMargin;
        else point.z = collider.b.z + kMargin;
    }

void Renderer::collide_cloth_particle(DirectX::XMFLOAT3& point) const {
        for (const ClothCollider& collider : cloth_colliders_) {
            if (collider.type == 1) collide_point_with_sphere(point, collider.a, collider.radius);
            else if (collider.type == 2) collide_point_with_capsule(point, collider);
            else if (collider.type == 3) collide_point_with_aabb(point, collider);
        }
    }

void Renderer::solve_cloth_constraint(ClothRuntime& cloth, const ClothConstraint& constraint) {
        DirectX::XMFLOAT3& a = cloth.positions[static_cast<size_t>(constraint.a)];
        DirectX::XMFLOAT3& b = cloth.positions[static_cast<size_t>(constraint.b)];
        DirectX::XMFLOAT3 delta = sub3(b, a);
        float length = length3(delta);
        if (length <= 1e-8f) return;
        float pin_a = constraint.a < static_cast<int>(cloth.pin_weights.size()) ? cloth.pin_weights[static_cast<size_t>(constraint.a)] : 0.0f;
        float pin_b = constraint.b < static_cast<int>(cloth.pin_weights.size()) ? cloth.pin_weights[static_cast<size_t>(constraint.b)] : 0.0f;
        float inv_a = std::max(0.0f, 1.0f - pin_a);
        float inv_b = std::max(0.0f, 1.0f - pin_b);
        float inv_sum = inv_a + inv_b;
        if (inv_sum <= 1e-6f) return;
        DirectX::XMFLOAT3 correction = mul3(delta, ((length - constraint.rest_length) / length) * constraint.stiffness);
        a = add3(a, mul3(correction, inv_a / inv_sum));
        b = sub3(b, mul3(correction, inv_b / inv_sum));
    }

void Renderer::pin_cloth_particles(ClothRuntime& cloth) {
        for (size_t index = 0; index < cloth.positions.size(); ++index) {
            float pin = index < cloth.pin_weights.size() ? std::clamp(cloth.pin_weights[index], 0.0f, 1.0f) : 0.0f;
            if (pin <= 0.0f) continue;
            const DirectX::XMFLOAT3& rest = cloth.rest_positions[index];
            DirectX::XMFLOAT3& point = cloth.positions[index];
            point.x = point.x * (1.0f - pin) + rest.x * pin;
            point.y = point.y * (1.0f - pin) + rest.y * pin;
            point.z = point.z * (1.0f - pin) + rest.z * pin;
        }
    }

DirectX::XMFLOAT3 Renderer::cloth_root_translation_for_batch(const PreviewBatch& batch) const {
        DirectX::XMFLOAT3 root(pan_x_, pan_y_, pan_z_);
        if (alignment_batch_editable(batch)) {
            root.x += alignment_.translation_total.x;
            root.y += alignment_.translation_total.y;
            root.z += alignment_.translation_total.z;
            auto part = alignment_.part_transforms.find(batch.source_submesh_index);
            if (part != alignment_.part_transforms.end()) {
                root.x += part->second.translation.x;
                root.y += part->second.translation.y;
                root.z += part->second.translation.z;
            }
        }
        return root;
    }

void Renderer::apply_cloth_root_motion(PreviewBatch& batch) {
        ClothRuntime& cloth = batch.cloth;
        if (!cloth.initialized || cloth.positions.empty()) return;
        bool part_non_translation_active = false;
        auto part = alignment_.part_transforms.find(batch.source_submesh_index);
        if (part != alignment_.part_transforms.end()) {
            constexpr float kEpsilon = 1.0e-6f;
            part_non_translation_active =
                std::abs(part->second.rotation.x) > kEpsilon
                || std::abs(part->second.rotation.y) > kEpsilon
                || std::abs(part->second.rotation.z) > kEpsilon
                || std::abs(part->second.scale.x - 1.0f) > kEpsilon
                || std::abs(part->second.scale.y - 1.0f) > kEpsilon
                || std::abs(part->second.scale.z - 1.0f) > kEpsilon;
        }
        const bool non_translation_active =
            alignment_batch_editable(batch)
            && (alignment_non_translation_transform_active() || part_non_translation_active);
        const DirectX::XMFLOAT3 root = cloth_root_translation_for_batch(batch);
        if (non_translation_active && !cloth.non_translation_reanchored) {
            cloth.positions = cloth.rest_positions;
            cloth.previous_positions = cloth.rest_positions;
            cloth.root_motion_initialized = false;
            cloth.non_translation_reanchored = true;
            apply_cloth_to_batch_vertices(batch);
        } else if (!non_translation_active) {
            cloth.non_translation_reanchored = false;
        }
        if (!cloth.root_motion_initialized) {
            cloth.last_root_translation = root;
            cloth.root_motion_initialized = true;
            return;
        }
        const DirectX::XMFLOAT3 delta = sub3(root, cloth.last_root_translation);
        cloth.last_root_translation = root;
        if (length3(delta) <= 1.0e-7f) return;
        for (size_t index = 0; index < cloth.positions.size(); ++index) {
            const float pin = index < cloth.pin_weights.size() ? std::clamp(cloth.pin_weights[index], 0.0f, 1.0f) : 0.0f;
            const DirectX::XMFLOAT3 local_delta = mul3(delta, -(1.0f - pin));
            cloth.positions[index] = add3(cloth.positions[index], local_delta);
            if (index < cloth.previous_positions.size()) {
                cloth.previous_positions[index] = add3(cloth.previous_positions[index], local_delta);
            }
        }
    }

void Renderer::apply_cloth_to_batch_vertices(PreviewBatch& batch) {
        ClothRuntime& cloth = batch.cloth;
        if (!cloth.initialized || batch.cpu_vertices.size() < static_cast<size_t>(batch.vertex_count) * 23u) return;
        for (int vertex_index = 0; vertex_index < batch.vertex_count; ++vertex_index) {
            int source_vertex = vertex_index < static_cast<int>(batch.cpu_source_vertices.size())
                ? batch.cpu_source_vertices[static_cast<size_t>(vertex_index)]
                : vertex_index;
            if (source_vertex < 0 || static_cast<size_t>(source_vertex) >= cloth.positions.size()) continue;
            const DirectX::XMFLOAT3& point = cloth.positions[static_cast<size_t>(source_vertex)];
            size_t offset = static_cast<size_t>(vertex_index) * 23u;
            batch.cpu_vertices[offset] = point.x;
            batch.cpu_vertices[offset + 1u] = point.y;
            batch.cpu_vertices[offset + 2u] = point.z;
            if (static_cast<size_t>(vertex_index) < batch.cpu_positions.size()) {
                batch.cpu_positions[static_cast<size_t>(vertex_index)] = point;
            }
        }
        for (int vertex_index = 0; vertex_index + 2 < batch.vertex_count; vertex_index += 3) {
            size_t a_offset = static_cast<size_t>(vertex_index) * 23u;
            size_t b_offset = static_cast<size_t>(vertex_index + 1) * 23u;
            size_t c_offset = static_cast<size_t>(vertex_index + 2) * 23u;
            DirectX::XMFLOAT3 a(batch.cpu_vertices[a_offset], batch.cpu_vertices[a_offset + 1u], batch.cpu_vertices[a_offset + 2u]);
            DirectX::XMFLOAT3 b(batch.cpu_vertices[b_offset], batch.cpu_vertices[b_offset + 1u], batch.cpu_vertices[b_offset + 2u]);
            DirectX::XMFLOAT3 c(batch.cpu_vertices[c_offset], batch.cpu_vertices[c_offset + 1u], batch.cpu_vertices[c_offset + 2u]);
            DirectX::XMFLOAT3 ab = sub3(b, a);
            DirectX::XMFLOAT3 ac = sub3(c, a);
            DirectX::XMFLOAT3 normal = normalize3(DirectX::XMFLOAT3(
                ab.y * ac.z - ab.z * ac.y,
                ab.z * ac.x - ab.x * ac.z,
                ab.x * ac.y - ab.y * ac.x));
            for (int corner = 0; corner < 3; ++corner) {
                size_t offset = static_cast<size_t>(vertex_index + corner) * 23u;
                batch.cpu_vertices[offset + 3u] = normal.x;
                batch.cpu_vertices[offset + 4u] = normal.y;
                batch.cpu_vertices[offset + 5u] = normal.z;
                batch.cpu_vertices[offset + 17u] = normal.x;
                batch.cpu_vertices[offset + 18u] = normal.y;
                batch.cpu_vertices[offset + 19u] = normal.z;
            }
        }
        if (context_ && batch.vertex_buffer) {
            D3D11_MAPPED_SUBRESOURCE mapped{};
            HRESULT hr = context_->Map(batch.vertex_buffer.Get(), 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
            if (SUCCEEDED(hr)) {
                std::memcpy(mapped.pData, batch.cpu_vertices.data(), batch.cpu_vertices.size() * sizeof(float));
                context_->Unmap(batch.vertex_buffer.Get(), 0);
            }
        }
    }

void Renderer::reset_cloth_runtime() {
        for (PreviewBatch& batch : batches_) {
            ClothRuntime& cloth = batch.cloth;
            if (!cloth.initialized || cloth.rest_positions.empty()) continue;
            cloth.positions = cloth.rest_positions;
            cloth.previous_positions = cloth.rest_positions;
            cloth.root_motion_initialized = false;
            cloth.non_translation_reanchored = false;
            cloth.last_root_translation = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            apply_cloth_to_batch_vertices(batch);
        }
        cloth_last_step_ = std::chrono::steady_clock::now();
    }

void Renderer::step_cloth_simulation() {
        if (!cloth_preview_active()) {
            cloth_last_step_ = std::chrono::steady_clock::now();
            return;
        }
        auto now = std::chrono::steady_clock::now();
        if (cloth_last_step_.time_since_epoch().count() == 0) {
            cloth_last_step_ = now;
            return;
        }
        float dt = static_cast<float>(std::chrono::duration<double>(now - cloth_last_step_).count());
        dt = std::clamp(dt, 1.0f / 240.0f, 1.0f / 30.0f);
        cloth_last_step_ = now;
        const float direction_radians = cloth_state_.wind_direction_degrees * 3.1415926535f / 180.0f;
        DirectX::XMFLOAT3 wind(
            std::cos(direction_radians) * cloth_state_.wind_strength,
            0.0f,
            std::sin(direction_radians) * cloth_state_.wind_strength);
        bool stepped = false;
        for (PreviewBatch& batch : batches_) {
            ClothRuntime& cloth = batch.cloth;
            if (!cloth.initialized || cloth.positions.empty()) continue;
            apply_cloth_root_motion(batch);
            for (size_t index = 0; index < cloth.positions.size(); ++index) {
                float pin = index < cloth.pin_weights.size() ? std::clamp(cloth.pin_weights[index], 0.0f, 1.0f) : 0.0f;
                if (pin >= 0.999f) {
                    cloth.positions[index] = cloth.rest_positions[index];
                    cloth.previous_positions[index] = cloth.rest_positions[index];
                    continue;
                }
                DirectX::XMFLOAT3 current = cloth.positions[index];
                DirectX::XMFLOAT3 previous = cloth.previous_positions[index];
                DirectX::XMFLOAT3 velocity = mul3(sub3(current, previous), std::clamp(1.0f - cloth.damping * dt * 0.35f, 0.0f, 0.995f));
                cloth.previous_positions[index] = current;
                DirectX::XMFLOAT3 acceleration(wind.x * cloth.wind_response, cloth.gravity, wind.z * cloth.wind_response);
                cloth.positions[index] = add3(add3(current, velocity), mul3(acceleration, dt * dt));
            }
            const int iterations = std::clamp(cloth.solver_iterations, 1, 64);
            for (int iteration = 0; iteration < iterations; ++iteration) {
                for (const ClothConstraint& constraint : cloth.constraints) {
                    solve_cloth_constraint(cloth, constraint);
                }
                pin_cloth_particles(cloth);
                if (cloth.collision_enabled && !cloth_colliders_.empty()) {
                    for (size_t index = 0; index < cloth.positions.size(); ++index) {
                        float pin = index < cloth.pin_weights.size() ? cloth.pin_weights[index] : 0.0f;
                        if (pin >= 0.999f) continue;
                        collide_cloth_particle(cloth.positions[index]);
                    }
                }
            }
            apply_cloth_to_batch_vertices(batch);
            stepped = true;
        }
        if (stepped) {
            ++stats_.cloth_simulation_steps;
        }
    }
