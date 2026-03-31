from typing import List


class Solution:
    def threeSum(self, nums: list[int]) -> list[list[int]]:
        if len(nums) < 3:
            return []
        nums.sort()
        res = []
        for i in range(len(nums)):
            if nums[i] > 0:
                return res
            if i > 0 and (nums[i - 1] == nums[i]):
                continue
            l = i + 1
            r = len(nums) - 1
            while l < r:
                if nums[i] + nums[r] + nums[l] == 0:
                    res.append([nums[i], nums[l], nums[r]])
                    while l < r and nums[l] == nums[l + 1]:
                        l += 1
                    while l < r and nums[r] == nums[r - 1]:
                        r -= 1
                    l += 1
                    r -= 1
                elif nums[i] + nums[r] + nums[l] > 0:
                    while l < r and nums[r] == nums[r - 1]:
                        r -= 1
                    r -= 1
                else:
                    while l < r and nums[l] == nums[l + 1]:
                        l += 1
                    l += 1

        return res


if __name__ == '__main__':
    s = Solution()
    res = s.threeSum([-1, 0, 1, 2, -1, -4])
    print(res)




