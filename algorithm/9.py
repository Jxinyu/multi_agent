from typing import List


class Solution:
    def subarraySum(self, nums: List[int], k: int) -> int:
        # 1, 1, 2, 1, 3, -2
        # 1, 1, 3, 4, -2 -3 3 2 3 -1 0
        # 1, 1, 2
        right = 0
        res = 0
        while right <= len(nums):
            index = right
            s = 0
            i = right
            while index < len(nums):
                s += nums[index]
                if s == k:
                    i = index
                index += 1
            if i == right:
                right += 1
                continue
            res += self.subarraySum(nums[right + 1: i + 1], k)
            right += i + 1
        if not nums:
            return 1
        return res


if __name__ == '__main__':
    print(Solution().subarraySum([1, 1, 2, 1, 3, -2], 3))
